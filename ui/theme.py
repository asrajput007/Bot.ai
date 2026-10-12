import streamlit as st

CSS = """
:root{
  --bg:#0B1020; --bg2:#10182A; --surface:#151F33; --surface2:#1B2740;
  --accent:#38BDF8; --accent2:#8B5CF6; --ok:#34D399; --warn:#FBBF24; --err:#F87171;
  --text:#F8FAFC; --muted:#A6B2C5; --border:#273449; --radius:12px;
  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px;
}
html, body, [class*="st-"], button, input, textarea{
  font-family: Inter, "Segoe UI Variable", "Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif;
}
[data-testid="stIconMaterial"], [data-testid="stIconMaterial"] *, [data-testid="stExpanderToggleIcon"], [data-testid="stExpanderToggleIcon"] *,
.material-symbols-rounded, [class*="material-symbols"]{
  font-family: "Material Symbols Rounded", "Material Symbols Outlined" !important;
}
.stApp{
  background:
    radial-gradient(900px 420px at 100% -8%, rgba(139,92,246,.12), transparent 60%),
    radial-gradient(800px 380px at -5% 0%, rgba(56,189,248,.08), transparent 60%),
    var(--bg);
  color:var(--text);
}
header[data-testid="stHeader"]{background:transparent;}
.block-container{padding:1.1rem 2rem 4rem; max-width:1560px;}
h1,h2,h3,h4{letter-spacing:-.012em; color:var(--text);}
h3{font-size:1.15rem; font-weight:650;}
p, li{line-height:1.65;}
[data-testid="stMarkdownContainer"] p{margin-bottom:.55rem;}
a{color:var(--accent);}
hr{border-color:var(--border);}

section[data-testid="stSidebar"]{background:var(--bg2); border-right:1px solid var(--border);}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a,
section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"]{
  border-radius:10px; padding:.5rem .75rem; margin:2px 0; color:var(--muted); font-weight:550;
  transition:background .15s, color .15s;
}
section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"]:hover{background:rgba(56,189,248,.08); color:var(--text);}
section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"][aria-current="page"]{
  background:linear-gradient(90deg, rgba(56,189,248,.18), rgba(139,92,246,.10));
  color:var(--text); box-shadow: inset 3px 0 0 var(--accent);
}

.go-title{font-size:1.75rem; font-weight:700; line-height:1.2; margin:0;}
.go-crumb{font-size:.78rem; color:var(--muted); letter-spacing:.04em; text-transform:uppercase; margin-bottom:2px;}
.go-sub{color:var(--muted); margin:4px 0 0; font-size:.95rem;}
.go-section{font-size:1.05rem; font-weight:650; margin:1.4rem 0 .2rem;}
.go-section-sub{color:var(--muted); font-size:.85rem; margin:0 0 .6rem;}
.go-muted{color:var(--muted); font-size:.85rem;}
.go-chip{display:inline-block; padding:3px 10px; margin:0 6px 6px 0; border-radius:999px; background:var(--surface2); border:1px solid var(--border); font-size:.8rem; color:var(--text);}

.go-grid{display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:var(--s3); margin:var(--s2) 0 var(--s3);}
.go-kpi{background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:var(--s4) 18px; min-height:104px;}
.go-kpi .label{font-size:.72rem; color:var(--muted); text-transform:uppercase; letter-spacing:.07em; font-weight:600;}
.go-kpi .value{font-size:2rem; font-weight:700; line-height:1.15; margin-top:6px; font-variant-numeric:tabular-nums;}
.go-kpi .caption{font-size:.8rem; color:var(--muted); margin-top:4px; line-height:1.4;}
.go-kpi.na .value{font-size:1.05rem; color:var(--muted); font-weight:600; margin-top:12px;}
.go-kpi.accent{border-color:rgba(56,189,248,.45); background:linear-gradient(180deg, rgba(56,189,248,.08), var(--surface));}

.go-badge{display:inline-flex; align-items:center; gap:6px; padding:2px 10px; border-radius:999px; font-size:.72rem; font-weight:650; border:1px solid var(--border); white-space:nowrap; line-height:1.6;}
.go-badge.success{color:var(--ok); background:rgba(52,211,153,.12); border-color:rgba(52,211,153,.35);}
.go-badge.warning{color:var(--warn); background:rgba(251,191,36,.12); border-color:rgba(251,191,36,.35);}
.go-badge.error{color:var(--err); background:rgba(248,113,113,.12); border-color:rgba(248,113,113,.35);}
.go-badge.info{color:var(--accent); background:rgba(56,189,248,.12); border-color:rgba(56,189,248,.35);}
.go-badge.accent{color:#C4B5FD; background:rgba(139,92,246,.14); border-color:rgba(139,92,246,.4);}
.go-badge.neutral{color:var(--muted); background:rgba(166,178,197,.08);}
.go-badges{display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end;}

.go-stages{display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:var(--s3); margin:var(--s2) 0 var(--s4);}
.go-stage{background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:var(--s3) var(--s4); position:relative;}
.go-stage .name{font-weight:650; font-size:.92rem;}
.go-stage .state{margin-top:6px; display:flex; align-items:center; gap:8px; font-size:.82rem; font-weight:650;}
.go-stage .detail{color:var(--muted); font-size:.78rem; margin-top:4px; min-height:1.1em;}
.go-stage[data-state="running"]{border-color:var(--accent); box-shadow:0 0 0 1px rgba(56,189,248,.4);}
.go-stage[data-state="completed"]{border-color:rgba(52,211,153,.4);}
.go-stage[data-state="revision"]{border-color:rgba(251,191,36,.5);}
.go-stage[data-state="failed"]{border-color:rgba(248,113,113,.5);}
.go-stage[data-state="queued"] .state{color:var(--muted);}
.go-stage[data-state="running"] .state{color:var(--accent);}
.go-stage[data-state="completed"] .state{color:var(--ok);}
.go-stage[data-state="revision"] .state{color:var(--warn);}
.go-stage[data-state="failed"] .state{color:var(--err);}
.go-spin{width:12px; height:12px; border-radius:50%; border:2px solid rgba(56,189,248,.3); border-top-color:var(--accent); animation:go-rot .9s linear infinite; display:inline-block;}
@keyframes go-rot{to{transform:rotate(360deg);}}

.go-scores{display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:var(--s2); margin:var(--s2) 0;}
.go-score{background:var(--bg2); border:1px solid var(--border); border-radius:10px; padding:10px 12px;}
.go-score .k{font-size:.7rem; color:var(--muted); text-transform:uppercase; letter-spacing:.06em;}
.go-score .v{font-size:1.45rem; font-weight:700; font-variant-numeric:tabular-nums;}
.go-score .v small{font-size:.8rem; color:var(--muted); font-weight:500;}
.go-score .bar{height:4px; border-radius:4px; background:var(--border); margin-top:6px; overflow:hidden;}
.go-score .bar span{display:block; height:100%; background:var(--accent);}
.go-score.low .bar span{background:var(--warn);}
.go-score.bad .bar span{background:var(--err);}
.go-overall{display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:8px;}
.go-overall .big{font-size:2.2rem; font-weight:700; font-variant-numeric:tabular-nums;}
.go-overall .big small{font-size:1rem; color:var(--muted); font-weight:500;}

.go-fields{display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:var(--s2) var(--s4); margin:var(--s2) 0;}
.go-field .k{font-size:.7rem; color:var(--muted); text-transform:uppercase; letter-spacing:.07em; font-weight:600;}
.go-field .v{font-size:.92rem; line-height:1.5; margin-top:2px;}

.go-empty{text-align:center; padding:28px 20px; border:1px dashed var(--border); border-radius:var(--radius); background:rgba(21,31,51,.5);}
.go-empty .t{font-weight:650; font-size:1rem;}
.go-empty .b{color:var(--muted); font-size:.9rem; margin-top:4px;}
.go-error{padding:14px 16px; border:1px solid rgba(248,113,113,.45); border-left:4px solid var(--err); border-radius:var(--radius); background:rgba(248,113,113,.08);}
.go-error .t{font-weight:650;}
.go-error .b{color:var(--muted); font-size:.9rem; margin-top:2px;}

.go-prose{max-width:74ch; line-height:1.75;}

.go-cal{width:100%; border-collapse:separate; border-spacing:4px; table-layout:fixed;}
.go-cal th{font-size:.72rem; color:var(--muted); text-transform:uppercase; letter-spacing:.07em; text-align:left; padding:4px 6px;}
.go-cal td{vertical-align:top; background:var(--surface); border:1px solid var(--border); border-radius:10px; height:104px; padding:6px; overflow:hidden;}
.go-cal td.out{background:transparent; border-style:dashed; opacity:.5;}
.go-cal td.today{border-color:var(--accent);}
.go-cal .d{font-size:.75rem; color:var(--muted); font-weight:650;}
.go-cal .it{display:block; margin-top:3px; padding:2px 6px; border-radius:6px; font-size:.7rem; line-height:1.35; background:rgba(56,189,248,.12); border-left:3px solid var(--accent); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
.go-cal .it.done{background:rgba(52,211,153,.12); border-left-color:var(--ok);}

.stButton > button, .stDownloadButton > button, [data-testid^="stBaseButton"]{
  border-radius:10px; font-weight:600; transition:border-color .15s, background .15s, transform .05s;
}
[data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-secondaryFormSubmit"]{
  background:var(--surface); border:1px solid var(--border); color:var(--text);
}
[data-testid="stBaseButton-secondary"]:hover, [data-testid="stBaseButton-secondaryFormSubmit"]:hover{
  border-color:var(--accent); background:var(--surface2); color:var(--text);
}
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"]{
  background:linear-gradient(135deg,#38BDF8,#6C8CF5 60%,#8B5CF6); border:0; color:#07101F;
}
[data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover{filter:brightness(1.08); color:#07101F;}
button:disabled{opacity:.45;}
button:focus-visible, a:focus-visible, [role="tab"]:focus-visible, input:focus-visible, textarea:focus-visible, [data-baseweb="select"]:focus-within{
  outline:2px solid var(--accent) !important; outline-offset:2px;
}
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div{
  background:var(--bg2) !important; border-color:var(--border) !important; border-radius:10px !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {border-radius:var(--radius);}
div[data-testid="stVerticalBlockBorderWrapper"]{border-color:var(--border) !important; background:rgba(21,31,51,.55); border-radius:var(--radius) !important;}
[data-testid="stExpander"] details{background:rgba(21,31,51,.55); border:1px solid var(--border); border-radius:var(--radius);}
[data-testid="stExpander"] summary{font-weight:600;}
button[role="tab"]{font-weight:600; color:var(--muted);}
button[role="tab"][aria-selected="true"]{color:var(--text);}
[data-testid="stMetric"]{background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:12px 14px;}
[data-testid="stDataFrame"]{border:1px solid var(--border); border-radius:var(--radius); overflow:hidden;}
[data-testid="stAlert"]{border-radius:var(--radius);}
[data-testid="stProgress"] div[role="progressbar"] > div{background:linear-gradient(90deg,var(--accent),var(--accent2));}

@media (max-width: 1000px){
  .block-container{padding:3.4rem 1rem 3rem;}
  .go-title{font-size:1.45rem;}
  .go-kpi .value{font-size:1.6rem;}
  .go-cal td{height:72px;}
}
@media (max-width: 640px){
  .go-grid{grid-template-columns:repeat(2,minmax(0,1fr));}
  .go-cal th{font-size:.6rem; padding:2px;}
  .go-cal td{height:56px; padding:3px;}
  .go-cal .it{font-size:.6rem;}
}
@media (prefers-reduced-motion: reduce){
  *, *::before, *::after{animation:none !important; transition:none !important; scroll-behavior:auto !important;}
  .go-spin{border-top-color:transparent; border-color:var(--accent);}
}
"""


def inject():
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)
