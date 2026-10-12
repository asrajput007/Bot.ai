import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from . import guardrails, prompts
from .errors import GuardrailViolation, LLMOutputError
from .schemas import Draft, JudgeVerdict, LeadAssets


class GraphState(TypedDict, total=False):
    client_id: str
    brief: str
    status: str
    reason: str
    prompts: dict
    draft: dict
    revision: int
    feedback: str
    parameters: dict
    rounds: Annotated[list, operator.add]
    assets: dict
    asset_issues: list
    guardrail_flags: Annotated[list, operator.add]
    usage_log: Annotated[list, operator.add]


def _usage_entry(stage, usage):
    return {"stage": stage, **usage.as_dict()}


def _join_feedback(automatic, verdict):
    lines = list(automatic) + list(verdict.issues) + list(verdict.required_revisions)
    if verdict.revision_instructions:
        lines.append(verdict.revision_instructions)
    return "\n".join(f"- {line}" for line in dict.fromkeys(lines))


def build_graph(llm, store, settings):
    def guard_input(state):
        try:
            cleaned = guardrails.check_brief(
                state["brief"], settings.brief_min_chars, settings.brief_max_chars
            )
            parameters = guardrails.check_parameters(state.get("parameters"))
            store.client(state["client_id"])
        except GuardrailViolation as exc:
            return {"status": "blocked", "reason": "; ".join(exc.issues), "guardrail_flags": exc.issues}
        return {"brief": cleaned, "parameters": parameters, "status": "validated", "revision": 0}

    def build_prompt(state):
        return {"prompts": prompts.inject_all(store, state["client_id"])}

    def strategist(state):
        message = prompts.strategist_message(
            state["brief"], state.get("draft"), state.get("feedback"), state.get("parameters")
        )
        draft, usage = llm.structured(
            Draft, state["prompts"]["strategist"], message, settings.strategist_temperature
        )
        return {
            "draft": draft.model_dump(),
            "revision": state.get("revision", 0) + 1,
            "usage_log": [_usage_entry("strategist", usage)],
        }

    def judge(state):
        client = store.client(state["client_id"])
        draft = Draft(**state["draft"])
        automatic = guardrails.check_draft(draft, client, store.universal, state["brief"])
        verdict, usage = llm.structured(
            JudgeVerdict,
            state["prompts"]["judge"],
            prompts.judge_message(state["brief"], draft, automatic, state.get("parameters")),
            settings.judge_temperature,
        )
        passed = guardrails.passes_policy(
            verdict, automatic, settings.min_score, settings.min_average
        )
        record = {
            "round": state["revision"],
            "draft": state["draft"],
            "scores": verdict.scores.model_dump(),
            "strengths": list(verdict.strengths),
            "issues": list(verdict.issues),
            "required_revisions": list(verdict.required_revisions),
            "optional_refinements": list(verdict.optional_refinements),
            "automatic_findings": automatic,
            "revision_instructions": verdict.revision_instructions,
            "passed": passed,
        }
        return {
            "rounds": [record],
            "status": "passed" if passed else "revise",
            "feedback": "" if passed else _join_feedback(automatic, verdict),
            "guardrail_flags": automatic,
            "usage_log": [_usage_entry("judge", usage)],
        }

    def route_after_judge(state):
        if state["status"] == "passed":
            return "lead_gen"
        if state["revision"] < settings.max_revisions:
            return "strategist"
        return "escalate"

    def lead_gen(state):
        client = store.client(state["client_id"])
        draft = Draft(**state["draft"])
        feedback = None
        usage_log = []
        flags = []
        assets = None
        issues = []
        for _ in range(settings.asset_attempts):
            try:
                candidate, usage = llm.structured(
                    LeadAssets,
                    state["prompts"]["lead_gen"],
                    prompts.lead_gen_message(state["draft"], feedback, state.get("parameters")),
                    settings.lead_temperature,
                )
            except LLMOutputError:
                issues = ["The AI service returned incomplete assets."]
                flags.extend(issues)
                feedback = "- Return every required field for every email, post and CTA.\n" + "\n".join(f"- {issue}" for issue in issues)
                continue
            assets = candidate
            usage_log.append(_usage_entry("lead_gen", usage))
            issues = guardrails.check_assets(assets, client, store.universal, state["brief"], draft)
            flags.extend(issues)
            if not issues:
                break
            feedback = "\n".join(f"- {issue}" for issue in issues)
        update = {
            "assets": assets.model_dump() if assets else None,
            "asset_issues": issues,
            "guardrail_flags": flags,
            "usage_log": usage_log,
            "status": "completed" if not issues else "escalated",
        }
        if issues:
            update["reason"] = "Lead assets failed output guardrails after retries; human review required."
        return update

    def escalate(state):
        return {
            "status": "escalated",
            "reason": f"Judge did not approve the draft after {state['revision']} revisions; human review required.",
        }

    graph = StateGraph(GraphState)
    graph.add_node("guard_input", guard_input)
    graph.add_node("build_prompt", build_prompt)
    graph.add_node("strategist", strategist)
    graph.add_node("judge", judge)
    graph.add_node("lead_gen", lead_gen)
    graph.add_node("escalate", escalate)
    graph.add_edge(START, "guard_input")
    graph.add_conditional_edges(
        "guard_input",
        lambda state: "stop" if state["status"] == "blocked" else "go",
        {"stop": END, "go": "build_prompt"},
    )
    graph.add_edge("build_prompt", "strategist")
    graph.add_edge("strategist", "judge")
    graph.add_conditional_edges(
        "judge",
        route_after_judge,
        {"lead_gen": "lead_gen", "strategist": "strategist", "escalate": "escalate"},
    )
    graph.add_edge("lead_gen", END)
    graph.add_edge("escalate", END)
    return graph.compile()


def run_stream(graph, state, sink, on_event=None):
    for mode, payload in graph.stream(state, stream_mode=["updates", "values"]):
        if mode == "values":
            sink.clear()
            sink.update(payload)
        elif on_event:
            for node, update in payload.items():
                on_event(node, update)
