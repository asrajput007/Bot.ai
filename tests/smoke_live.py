import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from growth_os.config import load_settings
from growth_os.service import GrowthService


def main():
    settings = replace(load_settings(), data_dir=Path(tempfile.mkdtemp()))
    service = GrowthService(settings)
    client_id = sys.argv[1] if len(sys.argv) > 1 else "northwind-fintech"
    brief = "Explain why settlement speed is a margin decision for exporters, and invite them to review their FX costs."
    result = service.run(service.operators()[0], client_id, brief, lambda node, update: print("->", node, update.get("status", "")))
    record = result["record"]
    print({key: record[key] for key in ("status", "revisions", "avg_score", "latency_s", "input_tokens", "output_tokens", "cost_usd", "guardrail_flags", "error")})
    for item in result["rounds"]:
        print(item["round"], item["passed"], item["scores"], item["automatic_findings"], item["issues"])
    print(result["assets"] and result["assets"]["ctas"])


main()
