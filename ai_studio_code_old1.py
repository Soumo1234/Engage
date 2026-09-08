#!/usr/bin/env python3
import html
import json
import requests
import time
from datetime import datetime, date, timedelta
from bs4 import BeautifulSoup
import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# 1. CONSTANTS & SYSTEM OPTIONS
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

DUMMY_DOCUMENTS = [
    {"id": "ENG-2026-04821", "title": "FY26 Basel III Capital Adequacy Examination", "regulator": "HKMA, PRA", "date": "2026-01-12", "status": "Open", "theme": "Prudential"},
    {"id": "ENG-2026-03912", "title": "Consumer Duty Outcomes Monitoring Review", "regulator": "FCA", "date": "2026-02-14", "status": "Draft", "theme": "Consumer Duty"},
    {"id": "ENG-2025-09214", "title": "Cross-Border Data Flows Enquiry", "regulator": "MAS", "date": "2025-11-30", "status": "Complete", "theme": "Data Privacy"},
    {"id": "ENG-2025-08102", "title": "AML Systems & Controls Assessment", "regulator": "FINMA", "date": "2025-10-05", "status": "Closed", "theme": "Financial Crime"}
]

DUMMY_CONTROLS = [
    {"eng_id": "ENG-2026-04821", "title": "FY26 Basel III Capital Adequacy", "ctrl_id": "CTRL-1077", "control": "C-CRED-44 Underwriting Standards", "status": "Partially Covered"},
    {"eng_id": "ENG-2026-03912", "title": "Consumer Duty Outcomes", "ctrl_id": "CTRL-2021", "control": "C-REG-01 Compliance Reporting", "status": "Covered"},
    {"eng_id": "ENG-2025-09214", "title": "Cross-Border Data Flows", "ctrl_id": "CTRL-3392", "control": "C-TECH-12 Data Privacy Shield", "status": "Gap"}
]

DUMMY_RESPONSES = [
    {"title": "Standard Basel III Clarification Letter", "category": "Capital Adequacy", "version": "v2.1", "usage": "14 times"},
    {"title": "Consumer Duty Data Request Template", "category": "Consumer Protection", "version": "v1.4", "usage": "28 times"},
    {"title": "Sanctions Screening False Positive Explanation", "category": "Financial Crime", "version": "v3.0", "usage": "45 times"}
]

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
    """Level 1: Extraction of details."""
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
    """Level 2: Task Generation."""
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
        return "".join([f"<div style='background:#fff; border:1px solid #eee; padding:10px; border-radius:6px; margin-bottom:8px; display:flex; justify-content:space-between;'><div><div style='font-size:11.5px; font-weight:700;'>{i['id']} {i['name']}</div><div style='font-size:10px; color:#666;'>{i.get('note','')}</div></div><span style='border:1px solid #0ca30c; color:#0ca30c; padding:2px 8px; border-radius:10px; font-size:9px; font-weight:800;'>COVERED</span></div>" for i in items])

    html_template = f"""
    <div style="font-family: sans-serif; padding:10px; background:#f9f9f7; color:#1e293b;">
        <div style="border-top: 1px solid #007377; background:#fff; padding:15px; border: 1px solid #e1e0d9; border-radius:4px; margin-bottom:20px;">
            <div style="font-size:14px; font-weight:700; color:#0d1b2a; margin-bottom:15px;">Engagement details</div>
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:15px;">
                <div>
                    <div style="font-size:10.5px; font-weight:600; color:#475569; margin-bottom:3px;">Engagement Title</div>
                    <div style="background:#f8fafc; border:1px solid #e1e0d9; padding:8px 12px; border-radius:4px; font-size:12px; display:flex; justify-content:space-between; color:#1e293b;">{r.get('title') or 'N/A'} <span style="color:#f59e0b;">🔒</span></div>
                    <br><div style="font-size:10.5px; font-weight:600; color:#475569; margin-bottom:3px;">Market</div>
                    <div style="background:#f8fafc; border:1px solid #e1e0d9; padding:8px 12px; border-radius:4px; font-size:12px; display:flex; justify-content:space-between; color:#1e293b;">{r.get('market') or 'N/A'} <span style="color:#f59e0b;">🔒</span></div>
                    <br><div style="font-size:10.5px; font-weight:600; color:#475569; margin-bottom:3px;">Engagement ID</div>
                    <div style="background:#f8fafc; border:1px solid #e1e0d9; padding:8px 12px; border-radius:4px; font-size:12px; display:flex; justify-content:space-between; color:#1e293b;">{r.get('engagement_id') or 'None'} <span style="color:#f59e0b;">🔒</span></div>
                </div>
                <div>
                    <div style="font-size:10.5px; font-weight:600; color:#475569; margin-bottom:3px;">Region(s)</div>
                    <div style="background:#f8fafc; border:1px solid #e1e0d9; padding:8px 12px; border-radius:4px; font-size:12px; display:flex; justify-content:space-between; color:#1e293b;">{r.get('regions') or 'N/A'} <span style="color:#f59e0b;">🔒</span></div>
                    <br><div style="font-size:10.5px; font-weight:600; color:#475569; margin-bottom:3px;">Regulator</div>
                    <div style="background:#f8fafc; border:1px solid #e1e0d9; padding:8px 12px; border-radius:4px; font-size:12px; display:flex; justify-content:space-between; color:#1e293b;">{r.get('regulator') or 'N/A'} <span style="color:#f59e0b;">🔒</span></div>
                    <br><div style="font-size:10.5px; font-weight:600; color:#475569; margin-bottom:3px;">Engagement Process Record ID</div>
                    <div style="background:#f8fafc; border:1px solid #e1e0d9; padding:8px 12px; border-radius:4px; font-size:12px; display:flex; justify-content:space-between; color:#1e293b;">{r.get('process_id') or 'None'} <span style="color:#f59e0b;">🔒</span></div>
                </div>
            </div>
            <div style="margin-top:15px; display:grid; grid-template-columns: 1fr 1fr; gap:15px;">
                <div style="background:#f8fafc; border:1px solid #e1e0d9; padding:10px; border-radius:4px; font-size:11px;">
                    <span style="color:#64748b;">LOB:</span> <b>{(r.get('lob_text') or 'N/A').replace(' > ', ' › ')}</b>
                </div>
                <div style="background:#f8fafc; border:1px solid #e1e0d9; padding:10px; border-radius:4px; font-size:11px;">
                    <span style="color:#64748b;">TAX:</span> <b>{(r.get('tax_text') or 'N/A').replace(' > ', ' › ')}</b>
                </div>
            </div>
        </div>
        <div style="background:#fff; border: 1px solid #e1e0d9; padding:20px; border-radius:4px;">
            <div style="font-size:15px; font-weight:700; color:#0d1b2a; margin-bottom:15px;">Controls In Scope [FR-4.5]</div>
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:30px;">
                <div>{render_items(lib_data['controls'])}</div>
                <div>{render_items(lib_data['policies'])}</div>
            </div>
            <div style="margin-top:15px; font-size:12px; color:#475569;">
                Control ID: <b>{r.get('control_id') or 'CTRL-1077'}</b>
            </div>
        </div>
    </div>
    """
    return html_template

# ---------------------------------------------------------------------------
# 4. MAIN APP ROUTING
# ---------------------------------------------------------------------------
def run_app():
    st.set_page_config(page_title="Reg Engagement", layout="wide")
    
    st.markdown("""
    <style>
        .udp-header { background:linear-gradient(135deg,#0d1b2a,#1b263b); color:#fff; padding:20px 24px; border-radius:12px; margin-bottom:20px; font-family:sans-serif; }
        .rationale-card { position: relative; margin-left: 45px; border: 1px solid #e1e0d9; border-radius: 8px; padding: 20px; margin-bottom: 25px; background: white; font-family: sans-serif; }
        .card-icon { position: absolute; left: -50px; top: 0; width: 34px; height: 34px; background: #0369a1; color: white; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; }
        .card-line { position: absolute; left: -34px; top: 34px; bottom: -25px; width: 2px; background: #e1e0d9; }
        .avatar { background:#134e4a; color:white; width:30px; height:30px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:11px; font-weight:700; border: 2px solid #fff; }
        .module-card { background:#fff; border:1px solid #e1e0d9; border-radius:10px; padding:20px; margin-bottom:15px; box-shadow:0 1px 3px rgba(0,0,0,0.02); }
    </style>
    """, unsafe_allow_html=True)

    if "data" not in st.session_state: st.session_state.data = None
    if "tasks" not in st.session_state: st.session_state.tasks = []
    if "status" not in st.session_state: st.session_state.status = "Draft"
    if "confirmed" not in st.session_state: st.session_state.confirmed = False

    # SIDEBAR
    with st.sidebar:
        st.subheader("Reg Engagement")
        menu = st.radio("Module", [
            "Engagement Creation",
            "Document Search",
            "Control Mapping",
            "Response Library"
        ])
        st.divider()
        api_key = st.text_input("Gemini API Key", type="password")
        model_id = st.text_input("Model ID", value="models/gemini-3.6-flash")

    if "Engagement Creation" in menu:
        st.markdown(f'<div class="udp-header"><h1>{menu}</h1><p style="color: #94a3b8; font-size: 13px; margin: 5px 0 0 0;">Reg Engagement Platform</p></div>', unsafe_allow_html=True)
        url_input = st.text_input("Engagement Letter URL")
        
        if st.button("Extract Engagement Details"):
            if not api_key: st.error("API Key required.")
            else:
                with st.spinner("Extracting Details..."):
                    st.session_state.data = process_engagement_extraction(url_input, api_key, model_id)
                    st.session_state.confirmed = False
                    st.session_state.tasks = []

        if st.session_state.data:
            d = st.session_state.data
            st.markdown(f"""
            <div style="background:#0d1b2a; padding:15px 25px; border-radius:12px 12px 0 0; display:flex; justify-content:space-between; align-items:center; color:white; font-family:sans-serif;">
                <div>
                    <div style="color:#898781; font-size:11px;">{d.get('engagement_id') or 'None'} &middot; {d.get('process_id') or 'None'}</div>
                    <div style="font-size:19px; font-weight:700;">{d.get('title') or 'Engagement'}</div>
                    <div style="margin-top:5px;"><span style="background:#fef3c7; color:#d97706; padding:3px 15px; border-radius:20px; font-size:11px; font-weight:600;">● {st.session_state.status}</span></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            col_h1, col_h2, col_h3 = st.columns([5, 1, 1])
            with col_h2:
                st.markdown("<div style='margin-top:-63px;'>", unsafe_allow_html=True)
                if st.button("Save draft", use_container_width=True): st.toast("Saved!")
                st.markdown("</div>", unsafe_allow_html=True)
            with col_h3:
                st.markdown("<div style='margin-top:-63px;'>", unsafe_allow_html=True)
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

            tabs_names = ["📋 Engagement Details", "💬 Decision feeds"]
            if st.session_state.confirmed: tabs_names.append("✅ Tasks")
            tabs = st.tabs(tabs_names)

            with tabs[0]:
                st.markdown('<div style="font-size:14px; font-weight:700; margin-bottom:10px;">Themes & Domain</div>', unsafe_allow_html=True)
                c_c1, c_c2 = st.columns(2)
                with c_c1: st.multiselect("Themes", THEMES_LIST, default=d.get('themes', []))
                with c_c2: st.multiselect("Business Domain", DOMAINS_LIST, default=d.get('domain', []))
                
                st.markdown('<div style="font-size:14px; font-weight:700; margin-top:20px; margin-bottom:10px;">Date Fields</div>', unsafe_allow_html=True)
                c_d1, c_d2 = st.columns(2)
                with c_d1: st.date_input("Internal deadline *", value=safe_date_parse(d.get('internal_deadline')))
                with c_d2: st.date_input("Submission deadline *", value=safe_date_parse(d.get('submission_deadline')))
                
                st.markdown('<div style="font-size:14px; font-weight:700; margin-top:20px; margin-bottom:10px;">Ownership & Status</div>', unsafe_allow_html=True)
                c_o1, c_o2 = st.columns(2)
                with c_o1:
                    st.markdown("""<div style="background:#f8fafc; border:1px solid #e1e0d9; padding:10px; border-radius:4px; display:flex; align-items:center; gap:12px; font-family:sans-serif;">
                        <div style="background:#134e4a; color:white; width:34px; height:34px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:700;">JD</div>
                        <div><div style="font-size:12.5px; font-weight:700;">John Doe 🔒</div><div style="font-size:10.5px; color:#64748b;">Regulatory Affairs</div></div>
                    </div>""", unsafe_allow_html=True)
                with c_o2: st.session_state.status = st.selectbox("Process Status", STATUS_OPTIONS, index=STATUS_OPTIONS.index(st.session_state.status))

                components.html(_get_dashboard_html(d), height=700)

            with tabs[1]:
                rationale = [("📄 Description", d.get('description','N/A')), ("🎯 Scope", d.get('scope','N/A')), ("📈 Impact", d.get('impact','N/A'))]
                for icon, txt in rationale:
                    st.markdown(f"""<div class="rationale-card"><div class="card-icon">{icon[0]}</div><div class="card-line"></div>
                        <div style="font-weight:700; color:#0d1b2a; font-size:13px; margin-bottom:5px;">{icon[2:]}</div>
                        <div style="font-size:13px; color:#334155; line-height:1.6; border:1px solid #f1f5f9; padding:15px; background:#fcfcfb;">{txt}</div>
                    </div>""", unsafe_allow_html=True)

            if st.session_state.confirmed:
                with tabs[2]:
                    st.markdown('<div style="font-size:18px; font-weight:800; margin-bottom:20px; color:#0d1b2a;">Strategic Task Roadmap</div>', unsafe_allow_html=True)
                    for i, t in enumerate(st.session_state.tasks, start=1):
                        with st.expander(f"Task {i}: {t.get('title','Task')}"):
                            tc1, tc2 = st.columns(2)
                            t['status'] = tc1.selectbox(f"Status T{i}", TASK_STATUS_OPTIONS, key=f"s_{i}")
                            t['date'] = tc2.date_input(f"Task Deadline Date T{i}", value=safe_date_parse(t.get('date')), key=f"d_{i}")
                            t['desc'] = st.text_area("Description", value=t.get('desc',''), key=f"de_{i}")
                            st.markdown(f'<div style="display:flex; justify-content:flex-end; align-items:center; gap:10px;"><span style="font-size:11px;">Owner: {t.get("owner")}</span><div class="avatar">{t.get("initials")}</div></div>', unsafe_allow_html=True)
                    if st.button("＋ Add Operational Task"):
                        st.session_state.tasks.append({"title": "Manual Item", "status": "Not Started", "date": "2026-12-01", "owner": "John Doe", "initials": "JD", "desc": ""})
                        st.rerun()

    elif "Document Search" in menu:
        st.markdown(f'<div class="udp-header"><h1>{menu}</h1><p style="color: #94a3b8; font-size: 13px; margin: 5px 0 0 0;">Reg Engagement Platform</p></div>', unsafe_allow_html=True)
        search_query = st.text_input("Search records by keyword, engagement ID, or regulator...", label_visibility="collapsed", placeholder="Search records...")
        st.markdown("<br>", unsafe_allow_html=True)
        for doc in DUMMY_DOCUMENTS:
            if search_query.lower() in doc['title'].lower() or search_query.lower() in doc['regulator'].lower() or not search_query:
                st.markdown(f"""
                <div class="module-card">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <div>
                            <span style="font-family:monospace; font-size:11px; background:#f1f5f9; padding:2px 6px; border-radius:4px;">{doc['id']}</span>
                            <h3 style="margin:5px 0 0 0; font-size:16px; color:#0d1b2a;">{doc['title']}</h3>
                        </div>
                        <span style="background:#e0f2fe; color:#0369a1; padding:2px 10px; border-radius:12px; font-size:10px; font-weight:700;">{doc['theme']}</span>
                    </div>
                    <div style="margin-top:10px; font-size:12px; color:#64748b; display:flex; gap:20px;">
                        <span>Regulator: <b>{doc['regulator']}</b></span>
                        <span>Date: <b>{doc['date']}</b></span>
                        <span>Status: <b>{doc['status']}</b></span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

    elif "Control Mapping" in menu:
        st.markdown(f'<div class="udp-header"><h1>{menu}</h1><p style="color: #94a3b8; font-size: 13px; margin: 5px 0 0 0;">Reg Engagement Platform</p></div>', unsafe_allow_html=True)
        for m in DUMMY_CONTROLS:
            badge_color = "#0ca30c" if m['status'] == "Covered" else ("#d97706" if m['status'] == "Partially Covered" else "#d03b3b")
            st.markdown(f"""
            <div class="module-card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <span style="font-size:11px; color:#64748b;">{m['eng_id']}</span>
                        <div style="font-size:15px; font-weight:700; color:#0d1b2a;">{m['title']}</div>
                    </div>
                    <span style="border:1px solid {badge_color}; color:{badge_color}; padding:3px 10px; border-radius:12px; font-size:10px; font-weight:800; text-transform:uppercase;">{m['status']}</span>
                </div>
                <div style="margin-top:12px; font-size:12px; background:#f8fafc; padding:8px 12px; border-radius:6px; display:flex; justify-content:space-between;">
                    <span>Linked Control ID: <b>{m['ctrl_id']}</b></span>
                    <span>Mapped Control: <b>{m['control']}</b></span>
                </div>
            </div>
            """, unsafe_allow_html=True)

    elif "Response Library" in menu:
        st.markdown(f'<div class="udp-header"><h1>{menu}</h1><p style="color: #94a3b8; font-size: 13px; margin: 5px 0 0 0;">Reg Engagement Platform</p></div>', unsafe_allow_html=True)
        for resp in DUMMY_RESPONSES:
            st.markdown(f"""
            <div class="module-card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <span style="font-size:10px; font-weight:700; background:#f1f5f9; color:#475569; padding:2px 8px; border-radius:4px; text-transform:uppercase;">{resp['category']}</span>
                        <div style="font-size:16px; font-weight:700; color:#0d1b2a; margin-top:5px;">{resp['title']}</div>
                    </div>
                    <span style="font-size:12px; color:#64748b;">Used <b>{resp['usage']}</b></span>
                </div>
                <div style="margin-top:12px; font-size:11.5px; color:#64748b; display:flex; justify-content:flex-end; border-top:1px solid #f1f5f9; padding-top:8px;">
                    <span>Version: <b>{resp['version']}</b></span>
                </div>
            </div>
            """, unsafe_allow_html=True)

if __name__ == "__main__":
    run_app()