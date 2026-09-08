#!/usr/bin/env python3
import json
import requests
import time
import pandas as pd
from datetime import datetime, date
from bs4 import BeautifulSoup
import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# 1. CONSTANTS, SYSTEM OPTIONS & JSON DUMMY DATA
# ---------------------------------------------------------------------------
TOTAL_STEPS = 12
STATUS_OPTIONS = ["Draft", "Planned", "Open", "Submitted to Regulator", "Complete", "Closed", "Cancelled"]
TASK_STATUS_OPTIONS = ["Not Started", "In Progress", "Blocked", "Complete"]
THEMES_LIST = ["Conduct Risk", "Consumer Duty", "Data Privacy", "Financial Crime", "Market Conduct", "Operational Resilience", "Prudential"]
DOMAINS_LIST = ["Retail Banking", "Wealth Management", "Markets", "Payments", "Wholesale Banking", "Technology", "Group Functions"]

MOCK_GRC_LIBRARY = {
    "Regulatory Compliance": {
        "controls": [{"id": "C-REG-01", "name": "Compliance Reporting", "coverage": "Covered", "note": "Standard automated reporting."}],
        "policies": [{"id": "P-REG-10", "name": "Interaction Standard", "coverage": "Covered", "note": "Adherence verified."}]
    },
    "Credit Risk": {
        "controls": [{"id": "C-CRED-44", "name": "Underwriting Standards", "coverage": "Partially Covered", "note": "Review required."}],
        "policies": [{"id": "P-CRED-01", "name": "Lending Policy", "coverage": "Covered", "note": "Aligned with standards."}]
    }
}

DUMMY_DATA_JSON = """
{
    "documents": [
        {"id": "ENG-2026-04821", "title": "FY26 Basel III Capital Adequacy Examination", "regulator": "HKMA, PRA", "date": "2026-01-12", "status": "Open", "theme": "Prudential"},
        {"id": "ENG-2026-03912", "title": "Consumer Duty Outcomes Monitoring Review", "regulator": "FCA", "date": "2026-02-14", "status": "Draft", "theme": "Consumer Duty"},
        {"id": "ENG-2025-09214", "title": "Cross-Border Data Flows Enquiry", "regulator": "MAS", "date": "2025-11-30", "status": "Complete", "theme": "Data Privacy"},
        {"id": "ENG-2025-08102", "title": "AML Systems & Controls Assessment", "regulator": "FINMA", "date": "2025-10-05", "status": "Closed", "theme": "Financial Crime"},
        {"id": "ENG-2026-05001", "title": "Operational Resilience Framework Audit", "regulator": "SEC", "date": "2026-03-01", "status": "Planned", "theme": "Operational Resilience"},
        {"id": "ENG-2026-05112", "title": "Algorithmic Trading Market Conduct Probe", "regulator": "BaFin", "date": "2026-04-15", "status": "Open", "theme": "Market Conduct"}
    ],
    "controls": [
        {"eng_id": "ENG-2026-04821", "title": "FY26 Basel III Capital Adequacy", "ctrl_id": "CTRL-1077", "control": "C-CRED-44 Underwriting Standards", "status": "Partially Covered"},
        {"eng_id": "ENG-2026-03912", "title": "Consumer Duty Outcomes", "ctrl_id": "CTRL-2021", "control": "C-REG-01 Compliance Reporting", "status": "Covered"},
        {"eng_id": "ENG-2025-09214", "title": "Cross-Border Data Flows", "ctrl_id": "CTRL-3392", "control": "C-TECH-12 Data Privacy Shield", "status": "Gap"},
        {"eng_id": "ENG-2026-05001", "title": "OpRes Framework Audit", "ctrl_id": "CTRL-5510", "control": "C-OPS-05 BCP Testing", "status": "Covered"},
        {"eng_id": "ENG-2026-05112", "title": "Algo Trading Probe", "ctrl_id": "CTRL-8821", "control": "C-MKT-99 Trade Surveillance", "status": "Partially Covered"}
    ],
    "responses": [
        {"title": "Standard Basel III Clarification Letter", "category": "Capital Adequacy", "version": "v2.1", "usage": "14", "last_updated": "2026-01-10", "status": "Reusable"},
        {"title": "Consumer Duty Data Request Template", "category": "Consumer Protection", "version": "v1.4", "usage": "28", "last_updated": "2026-02-01", "status": "Reusable"},
        {"title": "Sanctions Screening False Positive Explanation", "category": "Financial Crime", "version": "v3.0", "usage": "45", "last_updated": "2025-11-20", "status": "Reusable"},
        {"title": "Data Localization Exemption Request", "category": "Data Privacy", "version": "v1.1", "usage": "8", "last_updated": "2025-09-15", "status": "Reusable"},
        {"title": "Draft Algorithmic Model Risk Assessment", "category": "Market Conduct", "version": "v0.1", "usage": "0", "last_updated": "2026-03-22", "status": "Draft"},
        {"title": "BaFin Initial Inquiry Response Template", "category": "Market Conduct", "version": "v0.2", "usage": "0", "last_updated": "2026-04-05", "status": "Draft"}
    ]
}
"""
app_data = json.loads(DUMMY_DATA_JSON)
DUMMY_DOCUMENTS = app_data["documents"]
DUMMY_CONTROLS = app_data["controls"]
DUMMY_RESPONSES = app_data["responses"]

# ---------------------------------------------------------------------------
# 2. CORE UTILITIES
# ---------------------------------------------------------------------------
def safe_date_parse(date_str, fallback="2026-04-15"):
    if not date_str or not isinstance(date_str, str) or len(date_str) < 10:
        return date.fromisoformat(fallback)
    try:
        return date.fromisoformat(date_str[:10])
    except:
        return date.fromisoformat(fallback)

def call_gemini_with_retry(client, model_id, prompt, retries=5):
    for i in range(retries):
        try:
            response = client.models.generate_content(
                model=model_id, contents=prompt, 
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1)
            )
            return json.loads(response.text)
        except Exception as e:
            err = str(e).upper()
            if ("429" in err or "503" in err or "RESOURCE_EXHAUSTED" in err) and i < retries - 1:
                time.sleep(10); continue
            raise e

def process_engagement_extraction(url, api_key, model_id):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(separator=' ', strip=True)[:8000]
        client = genai.Client(api_key=api_key)
        prompt = f"""
        Analyze: {text}. Return JSON: 
        title, regions, market, regulator, engagement_id, process_id, start_date, 
        themes (list from {THEMES_LIST}), domain (list from {DOMAINS_LIST}), 
        lob_text, tax_text, description, scope, impact, internal_deadline, submission_deadline, control_id.
        """
        ai_data = call_gemini_with_retry(client, model_id, prompt)
        ai_data['themes'] = [t for t in (ai_data.get('themes') or []) if t in THEMES_LIST]
        ai_data['domain'] = [d for d in (ai_data.get('domain') or []) if d in DOMAINS_LIST]
        return ai_data
    except Exception as e:
        st.error(f"AI Extraction Failure: {e}"); return None

def generate_tasks_for_engagement(api_key, model_id, engagement_data):
    try:
        client = genai.Client(api_key=api_key)
        prompt = f"Based on: {json.dumps(engagement_data)}, generate 3 specific operational tasks. JSON: ai_tasks (list of dicts with title, desc, date, owner, initials)."
        ai_res = call_gemini_with_retry(client, model_id, prompt)
        tasks = []
        for t in (ai_res.get('ai_tasks') or []):
            if isinstance(t, dict):
                t.setdefault("status", "Not Started")
                tasks.append(t)
        return tasks
    except Exception as e:
        st.error(f"Task Error: {e}"); return []

# ---------------------------------------------------------------------------
# 3. UI RENDERING
# ---------------------------------------------------------------------------
def _get_dashboard_html(r):
    tax_search_val = (r.get('tax_text') or '')
    l1_tax = "Regulatory Compliance" if "Compliance" in tax_search_val else "Credit Risk"
    lib_data = MOCK_GRC_LIBRARY.get(l1_tax, MOCK_GRC_LIBRARY["Regulatory Compliance"])
    
    def render_items(items):
        return "".join([f"<div style='background:#ffffff; border:1px solid #e2e8f0; padding:12px; border-radius:8px; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center; box-shadow: 0 1px 2px rgba(0,0,0,0.02);'><div><div style='font-size:12px; font-weight:600; color:#1e293b;'>{i['id']} {i['name']}</div><div style='font-size:11px; color:#64748b; margin-top:2px;'>{i.get('note','')}</div></div><span style='background:#f0fdf4; border:1px solid #bbf7d0; color:#166534; padding:4px 10px; border-radius:12px; font-size:10px; font-weight:600;'>COVERED</span></div>" for i in items])

    html_template = f"""
    <div style="font-family: 'Inter', sans-serif; padding:10px; color:#0f172a;">
        <div style="background:#ffffff; padding:20px; border: 1px solid #e2e8f0; border-radius:12px; margin-bottom:24px; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
            <div style="font-size:16px; font-weight:600; color:#0f172a; margin-bottom:18px; border-bottom:1px solid #f1f5f9; padding-bottom:10px;">Engagement Core Details</div>
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:20px;">
                <div>
                    <div style="font-size:11px; font-weight:600; color:#64748b; margin-bottom:6px; text-transform:uppercase;">Engagement Title</div>
                    <div style="background:#f8fafc; border:1px solid #f1f5f9; padding:10px 14px; border-radius:6px; font-size:13px; color:#334155; margin-bottom:16px;">{r.get('title') or 'N/A'}</div>
                    
                    <div style="font-size:11px; font-weight:600; color:#64748b; margin-bottom:6px; text-transform:uppercase;">Market</div>
                    <div style="background:#f8fafc; border:1px solid #f1f5f9; padding:10px 14px; border-radius:6px; font-size:13px; color:#334155; margin-bottom:16px;">{r.get('market') or 'N/A'}</div>
                    
                    <div style="font-size:11px; font-weight:600; color:#64748b; margin-bottom:6px; text-transform:uppercase;">Engagement ID</div>
                    <div style="background:#f8fafc; border:1px solid #f1f5f9; padding:10px 14px; border-radius:6px; font-size:13px; color:#334155;">{r.get('engagement_id') or 'None'}</div>
                </div>
                <div>
                    <div style="font-size:11px; font-weight:600; color:#64748b; margin-bottom:6px; text-transform:uppercase;">Region(s)</div>
                    <div style="background:#f8fafc; border:1px solid #f1f5f9; padding:10px 14px; border-radius:6px; font-size:13px; color:#334155; margin-bottom:16px;">{r.get('regions') or 'N/A'}</div>
                    
                    <div style="font-size:11px; font-weight:600; color:#64748b; margin-bottom:6px; text-transform:uppercase;">Regulator</div>
                    <div style="background:#f8fafc; border:1px solid #f1f5f9; padding:10px 14px; border-radius:6px; font-size:13px; color:#334155; margin-bottom:16px;">{r.get('regulator') or 'N/A'}</div>
                    
                    <div style="font-size:11px; font-weight:600; color:#64748b; margin-bottom:6px; text-transform:uppercase;">Process Record ID</div>
                    <div style="background:#f8fafc; border:1px solid #f1f5f9; padding:10px 14px; border-radius:6px; font-size:13px; color:#334155;">{r.get('process_id') or 'None'}</div>
                </div>
            </div>
            <div style="margin-top:20px; display:grid; grid-template-columns: 1fr 1fr; gap:20px;">
                <div style="background:#f8fafc; border:1px solid #f1f5f9; padding:12px; border-radius:6px; font-size:12px;">
                    <span style="color:#64748b;">Line of Business:</span> <b style="color:#0f172a;">{(r.get('lob_text') or 'N/A').replace(' > ', ' › ')}</b>
                </div>
                <div style="background:#f8fafc; border:1px solid #f1f5f9; padding:12px; border-radius:6px; font-size:12px;">
                    <span style="color:#64748b;">Taxonomy:</span> <b style="color:#0f172a;">{(r.get('tax_text') or 'N/A').replace(' > ', ' › ')}</b>
                </div>
            </div>
        </div>
        <div style="background:#ffffff; border: 1px solid #e2e8f0; padding:20px; border-radius:12px; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
            <div style="font-size:16px; font-weight:600; color:#0f172a; margin-bottom:18px; border-bottom:1px solid #f1f5f9; padding-bottom:10px;">Controls In Scope</div>
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:24px;">
                <div>
                    <div style="font-size:12px; font-weight:600; color:#64748b; margin-bottom:10px;">Primary Controls</div>
                    {render_items(lib_data['controls'])}
                </div>
                <div>
                    <div style="font-size:12px; font-weight:600; color:#64748b; margin-bottom:10px;">Associated Policies</div>
                    {render_items(lib_data['policies'])}
                </div>
            </div>
            <div style="margin-top:20px; font-size:13px; color:#475569; background:#f8fafc; padding:12px; border-radius:6px; border:1px solid #f1f5f9;">
                Linked Control ID: <b style="color:#0f172a;">{r.get('control_id') or 'CTRL-1077'}</b>
            </div>
        </div>
    </div>
    """
    return html_template

# ---------------------------------------------------------------------------
# 4. MAIN APP ROUTING
# ---------------------------------------------------------------------------
def run_app():
    st.set_page_config(page_title="Reg Engagement", layout="wide", page_icon="🏦")
    
    st.markdown("""
    <style>
        .udp-header { background: linear-gradient(135deg, #1e293b, #334155); color: #ffffff; padding: 24px; border-radius: 12px; margin-bottom: 24px; font-family: 'Inter', sans-serif; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }
        .rationale-card { position: relative; margin-left: 50px; border: 1px solid #e2e8f0; border-radius: 12px; padding: 24px; margin-bottom: 24px; background: #ffffff; font-family: 'Inter', sans-serif; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
        .card-icon { position: absolute; left: -50px; top: 0; width: 36px; height: 36px; background: #0284c7; color: white; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 16px; box-shadow: 0 2px 4px rgba(2, 132, 199, 0.3); }
        .card-line { position: absolute; left: -33px; top: 40px; bottom: -30px; width: 2px; background: #e2e8f0; }
        .avatar { background: #0f766e; color: white; width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; border: 2px solid #ffffff; box-shadow: 0 1px 2px rgba(0,0,0,0.1); }
        .module-card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; margin-bottom: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.02); transition: transform 0.2s ease, box-shadow 0.2s ease; display: flex; flex-direction: column; gap: 12px;}
        .module-card:hover { transform: translateY(-2px); box-shadow: 0 6px 12px rgba(0,0,0,0.08); border-color: #cbd5e1; }
        .stDataFrame { border-radius: 8px; border: 1px solid #e2e8f0; }
    </style>
    """, unsafe_allow_html=True)

    if "data" not in st.session_state: st.session_state.data = None
    if "tasks" not in st.session_state: st.session_state.tasks = []
    if "status" not in st.session_state: st.session_state.status = "Draft"
    if "confirmed" not in st.session_state: st.session_state.confirmed = False

    with st.sidebar:
        st.title("🏦 Reg Engagement")
        st.markdown("<br>", unsafe_allow_html=True)
        menu = st.radio("Navigation", [
            "Engagement Creation",
            "Document Search",
            "Control Mapping",
            "Response Library"
        ], label_visibility="collapsed")
        
        st.divider()
        st.caption("⚙️ API Configuration")
        api_key = st.text_input("Gemini API Key", type="password", placeholder="Enter key...")
        model_id = st.text_input("Model ID", value="models/gemini-3.6-flash")

    if "Engagement Creation" in menu:
        st.markdown(f'<div class="udp-header"><h1 style="margin:0; font-size:28px;">{menu}</h1></div>', unsafe_allow_html=True)
        
        with st.container(border=True):
            url_input = st.text_input("Engagement Letter URL", placeholder="https://...")
            if st.button("Extract Engagement Details", type="primary"):
                if not api_key: st.error("API Key required.")
                else:
                    with st.spinner("Extracting Details..."):
                        st.session_state.data = process_engagement_extraction(url_input, api_key, model_id)
                        st.session_state.confirmed = False
                        st.session_state.tasks = []

        if st.session_state.data:
            d = st.session_state.data
            st.markdown(f"""
            <div style="background: #0f172a; padding: 24px; border-radius: 12px 12px 0 0; display: flex; justify-content: space-between; align-items: center; color: white; font-family: 'Inter', sans-serif; margin-top: 20px;">
                <div>
                    <div style="color: #94a3b8; font-size: 12px; font-weight: 500; margin-bottom: 4px;">{d.get('engagement_id') or 'None'} &middot; {d.get('process_id') or 'None'}</div>
                    <div style="font-size: 22px; font-weight: 600; letter-spacing: -0.5px;">{d.get('title') or 'Engagement'}</div>
                    <div style="margin-top: 10px;"><span style="background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); padding: 4px 12px; border-radius: 16px; font-size: 11px; font-weight: 600;">● {st.session_state.status}</span></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            col_h1, col_h2, col_h3 = st.columns([5, 1.2, 1.2])
            with col_h2:
                st.markdown("<div style='margin-top:-70px;'>", unsafe_allow_html=True)
                if st.button("Save draft", use_container_width=True): st.toast("Saved!")
                st.markdown("</div>", unsafe_allow_html=True)
            with col_h3:
                st.markdown("<div style='margin-top:-70px;'>", unsafe_allow_html=True)
                btn_lbl = "Submit to Regulators" if st.session_state.confirmed else "Task Creation"
                if st.button(btn_lbl, type="primary", use_container_width=True):
                    if not st.session_state.confirmed:
                        st.session_state.confirmed = True
                        with st.spinner("Generating Tasks..."):
                            st.session_state.tasks = generate_tasks_for_engagement(api_key, model_id, d)
                            st.session_state.status = "Open"
                            st.rerun()
                    else:
                        st.success("Record submitted successfully.")
                        st.balloons()
                st.markdown("</div>", unsafe_allow_html=True)

            tabs_names = ["📋 Engagement Details", "💬 Decision Feeds"]
            if st.session_state.confirmed: tabs_names.append("✅ Action Tasks")
            engage_tabs = st.tabs(tabs_names)

            with engage_tabs[0]:
                with st.container(border=True):
                    st.subheader("Themes & Domain")
                    c_c1, c_c2 = st.columns(2)
                    with c_c1: st.multiselect("Themes", THEMES_LIST, default=d.get('themes', []))
                    with c_c2: st.multiselect("Business Domain", DOMAINS_LIST, default=d.get('domain', []))
                    
                    st.divider()
                    st.subheader("Timeline & Ownership")
                    c_d1, c_d2, c_o2 = st.columns([1, 1, 1])
                    with c_d1: st.date_input("Internal deadline *", value=safe_date_parse(d.get('internal_deadline')))
                    with c_d2: st.date_input("Submission deadline *", value=safe_date_parse(d.get('submission_deadline')))
                    with c_o2: st.session_state.status = st.selectbox("Process Status", STATUS_OPTIONS, index=STATUS_OPTIONS.index(st.session_state.status))
                    
                components.html(_get_dashboard_html(d), height=650)

            with engage_tabs[1]:
                st.markdown("<br>", unsafe_allow_html=True)
                rationale = [("📄 Description", d.get('description','N/A')), ("🎯 Scope", d.get('scope','N/A')), ("📈 Impact", d.get('impact','N/A'))]
                for icon, txt in rationale:
                    st.markdown(f"""<div class="rationale-card"><div class="card-icon">{icon[0]}</div><div class="card-line"></div>
                        <div style="font-weight:600; color:#0f172a; font-size:14px; margin-bottom:8px;">{icon[2:]}</div>
                        <div style="font-size:13px; color:#475569; line-height:1.6; border:1px solid #f1f5f9; padding:16px; background:#f8fafc; border-radius: 8px;">{txt}</div>
                    </div>""", unsafe_allow_html=True)

            if st.session_state.confirmed:
                with engage_tabs[2]:
                    st.markdown("<br>", unsafe_allow_html=True)
                    for i, t in enumerate(st.session_state.tasks, start=1):
                        with st.expander(f"Task {i}: {t.get('title','Task')}", expanded=True):
                            tc1, tc2 = st.columns(2)
                            t['status'] = tc1.selectbox(f"Status", TASK_STATUS_OPTIONS, key=f"s_{i}")
                            t['date'] = tc2.date_input(f"Deadline", value=safe_date_parse(t.get('date')), key=f"d_{i}")
                            t['desc'] = st.text_area("Description", value=t.get('desc',''), key=f"de_{i}")
                            st.markdown(f'<div style="display:flex; justify-content:flex-end; align-items:center; gap:12px; margin-top: 10px;"><span style="font-size:12px; color: #64748b; font-weight: 500;">Assignee: {t.get("owner")}</span><div class="avatar">{t.get("initials")}</div></div>', unsafe_allow_html=True)
                    if st.button("＋ Add Operational Task"):
                        st.session_state.tasks.append({"title": "Manual Item", "status": "Not Started", "date": "2026-12-01", "owner": "John Doe", "initials": "JD", "desc": ""})
                        st.rerun()

    elif "Document Search" in menu:
        st.markdown(f'<div class="udp-header"><h1 style="margin:0; font-size:28px;">{menu}</h1></div>', unsafe_allow_html=True)
        search_query = st.text_input("Search records by keyword, engagement ID, or regulator...", label_visibility="collapsed", placeholder="🔍 Search records...")
        st.markdown("<br>", unsafe_allow_html=True)
        
        filtered_docs = [doc for doc in DUMMY_DOCUMENTS if search_query.lower() in doc['title'].lower() or search_query.lower() in doc['regulator'].lower() or not search_query]
        
        if filtered_docs:
            df_docs = pd.DataFrame(filtered_docs)
            df_docs.rename(columns={'id': 'Engagement ID', 'title': 'Title', 'regulator': 'Regulator', 'date': 'Target Date', 'status': 'Status', 'theme': 'Theme'}, inplace=True)
            st.dataframe(df_docs, use_container_width=True, hide_index=True)
        else:
            st.info("No documents match your search criteria.")

    elif "Control Mapping" in menu:
        st.markdown(f'<div class="udp-header"><h1 style="margin:0; font-size:28px;">{menu}</h1></div>', unsafe_allow_html=True)
        
        df_controls = pd.DataFrame(DUMMY_CONTROLS)
        df_controls.rename(columns={'eng_id': 'Engagement ID', 'title': 'Engagement Title', 'ctrl_id': 'Control ID', 'control': 'Mapped Control', 'status': 'Coverage Status'}, inplace=True)
        
        col_c1, col_c2 = st.columns([4, 1])
        with col_c1:
            st.dataframe(df_controls, use_container_width=True, hide_index=True)
        with col_c2:
            st.metric("Total Controls", len(DUMMY_CONTROLS))
            st.metric("Coverage Gaps", sum(1 for c in DUMMY_CONTROLS if c['status'] == 'Gap'))

    elif "Response Library" in menu:
        st.markdown(f'<div class="udp-header"><h1 style="margin:0; font-size:28px;">{menu}</h1></div>', unsafe_allow_html=True)
        
        tabs = st.tabs(["Reusable Response", "Draft"])
        
        reusable_resps = [r for r in DUMMY_RESPONSES if r.get('status', 'Reusable') == 'Reusable']
        draft_resps = [r for r in DUMMY_RESPONSES if r.get('status') == 'Draft']
        
        def render_response_cards(responses):
            if not responses:
                st.info("No responses found in this category.")
            for resp in responses:
                st.markdown(f"""
                <div class="module-card">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                        <div>
                            <span style="font-size: 10px; font-weight: 600; background: #e2e8f0; color: #475569; padding: 4px 10px; border-radius: 6px; text-transform: uppercase; letter-spacing: 0.5px;">{resp['category']}</span>
                            <div style="font-size: 17px; font-weight: 600; color: #0f172a; margin-top: 10px;">{resp['title']}</div>
                        </div>
                        <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 8px;">
                            <span style="font-size: 12px; color: #64748b; background: #f8fafc; padding: 4px 10px; border-radius: 16px; border: 1px solid #f1f5f9;">Used <b style="color: #0284c7;">{resp['usage']} times</b></span>
                            <span style="font-size: 11px; color: #94a3b8; font-weight: 500;">{resp['version']}</span>
                        </div>
                    </div>
                    <div style="margin-top: 8px; font-size: 12px; color: #64748b; display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #f1f5f9; padding-top: 12px;">
                        <span>Last Updated: <b style="color: #334155;">{resp['last_updated']}</b></span>
                        <a href="#" style="color: #0284c7; text-decoration: none; font-weight: 600;">Download Template ⬇</a>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
        with tabs[0]:
            render_response_cards(reusable_resps)
            
        with tabs[1]:
            render_response_cards(draft_resps)

if __name__ == "__main__":
    run_app()