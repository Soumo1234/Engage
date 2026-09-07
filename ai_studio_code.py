#!/usr/bin/env python3
import html
import json
import requests
import time
from datetime import datetime, date
from bs4 import BeautifulSoup
import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# 1. CONSTANTS & SYSTEM OPTIONS
# ---------------------------------------------------------------------------
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

def process_engagement(url, api_key, model_id):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(separator=' ', strip=True)[:8000]
        client = genai.Client(api_key=api_key)
        prompt = f"""
        Analyze: {text}. Return JSON for: title, engagement_id, process_id, market, regions, regulator, 
        start_date, themes (list from {THEMES_LIST}), domain (list from {DOMAINS_LIST}), lob_text, tax_text, 
        description, scope, impact, internal_deadline, submission_deadline,
        ai_tasks (list of dicts with title, desc, date, owner, initials).
        """
        ai_data = call_gemini_with_retry(client, model_id, prompt)
        
        # Validation for UI
        ai_data['themes'] = [t for t in ai_data.get('themes', []) if t in THEMES_LIST]
        ai_data['domain'] = [d for d in ai_data.get('domain', []) if d in DOMAINS_LIST]
        
        tasks = []
        for i, t in enumerate(ai_data.get('ai_tasks', [])):
            if isinstance(t, str):
                tasks.append({"title": t, "desc": "Action required.", "status": "Not Started", "date": "2026-10-15", "owner": "John Doe", "initials": "JD"})
            else:
                t.setdefault("status", "Not Started")
                t.setdefault("desc", "Detailed review required.")
                tasks.append(t)
        ai_data['ai_tasks'] = tasks
        return ai_data
    except Exception as e:
        st.error(f"AI Failure: {e}"); return None

# ---------------------------------------------------------------------------
# 3. DASHBOARD HTML RENDERING (With Key Dates Integration)
# ---------------------------------------------------------------------------
def _get_dashboard_html(r):
    l1_tax = "Regulatory Compliance" if "Compliance" in r.get('tax_text', '') else "Credit Risk"
    lib_data = MOCK_GRC_LIBRARY.get(l1_tax, MOCK_GRC_LIBRARY["Regulatory Compliance"])
    
    # Format dates for display DD-MM-YYYY
    int_dt = safe_date_parse(r.get('internal_deadline')).strftime("%d-%m-%Y")
    sub_dt = safe_date_parse(r.get('submission_deadline')).strftime("%d-%m-%Y")

    def render_items(items):
        return "".join([f"<div style='background:#fff; border:1px solid #eee; padding:10px; border-radius:6px; margin-bottom:8px; display:flex; justify-content:space-between;'><div><div style='font-size:11.5px; font-weight:700;'>{i['id']} {i['name']}</div><div style='font-size:10px; color:#666;'>{i.get('note','')}</div></div><span style='border:1px solid #0ca30c; color:#0ca30c; padding:2px 8px; border-radius:10px; font-size:9px; font-weight:800;'>COVERED</span></div>" for i in items])

    html_template = f"""
    <div style="font-family: sans-serif; padding:10px; background:#f9f9f7; color:#1e293b;">
        
        <!-- SECTION: ENGAGEMENT DETAILS -->
        <div style="border-top: 1px solid #007377; background:#fff; padding:15px; border: 1px solid #e1e0d9; border-radius:4px; margin-bottom:20px;">
            <div style="font-size:14px; font-weight:700; color:#0d1b2a; margin-bottom:15px;">Engagement details</div>
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:15px;">
                <div>
                    <div style="font-size:10.5px; font-weight:600; color:#475569; margin-bottom:3px;">Engagement Title</div>
                    <div style="background:#fff; border:1px solid #e1e0d9; padding:8px 12px; border-radius:4px; font-size:12px; display:flex; justify-content:space-between; color:#1e293b;">{r.get('title')} <span style="color:#f59e0b;">🔒</span></div>
                </div>
                <div>
                    <div style="font-size:10.5px; font-weight:600; color:#475569; margin-bottom:3px;">Regulator</div>
                    <div style="background:#fff; border:1px solid #e1e0d9; padding:8px 12px; border-radius:4px; font-size:12px; display:flex; justify-content:space-between; color:#1e293b;">{r.get('regulator')} <span style="color:#f59e0b;">🔒</span></div>
                </div>
            </div>
            <br>
            <div style="background:#f8fafc; border:1px solid #e1e0d9; padding:10px; border-radius:4px; font-size:11px;">
                <b>LOB:</b> {r.get('lob_text', 'N/A').replace(' > ', ' › ')}
            </div>
        </div>

        <!-- SECTION: KEY DATES (EXACT MATCH TO SCREENSHOT) -->
        <div style="background:#fff; border: 1px solid #e1e0d9; padding:20px; border-radius:4px; margin-bottom:20px;">
            <div style="font-size:9px; font-weight:800; color:#898781; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:5px;">KEY DATES</div>
            <div style="font-size:14px; font-weight:700; color:#0d1b2a; margin-bottom:15px;">Date Fields</div>
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:20px;">
                <div>
                    <div style="font-size:11px; font-weight:700; color:#475569; margin-bottom:5px;">Internal deadline <span style="color:#d03b3b;">*</span></div>
                    <div style="border:1px solid #e1e0d9; padding:10px 14px; border-radius:4px; font-size:13.5px; display:flex; justify-content:space-between; align-items:center; color:#1e293b;">
                        {int_dt} <span style="opacity:0.4;">📅</span>
                    </div>
                    <div style="font-size:10.5px; color:#64748b; margin-top:6px;">Manually entered/updated by the Primary Regulatory Workflow Owner.</div>
                </div>
                <div>
                    <div style="font-size:11px; font-weight:700; color:#475569; margin-bottom:5px;">Submission deadline <span style="color:#d03b3b;">*</span></div>
                    <div style="border:1px solid #e1e0d9; padding:10px 14px; border-radius:4px; font-size:13.5px; display:flex; justify-content:space-between; align-items:center; color:#1e293b;">
                        {sub_dt} <span style="opacity:0.4;">📅</span>
                    </div>
                    <div style="font-size:10.5px; color:#64748b; margin-top:6px;">Manually entered/updated by the Primary Regulatory Workflow Owner.</div>
                </div>
            </div>
            <div style="margin-top:20px; width:48.5%;">
                <div style="font-size:11px; font-weight:700; color:#475569; margin-bottom:5px;">Actual / Revised submission date</div>
                <div style="border:1px solid #e1e0d9; padding:10px 14px; border-radius:4px; font-size:13.5px; display:flex; justify-content:space-between; align-items:center; color:#94a3b8;">
                    dd-mm-yyyy <span style="opacity:0.4;">📅</span>
                </div>
                <div style="font-size:10.5px; color:#64748b; margin-top:6px;">Optional.</div>
            </div>
        </div>

        <!-- SECTION: CONTROLS -->
        <div style="background:#fff; border: 1px solid #e1e0d9; padding:20px; border-radius:4px;">
            <div style="font-size:15px; font-weight:700; color:#0d1b2a; margin-bottom:15px;">Controls In Scope [FR-4.5]</div>
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:30px;">
                <div><div style="font-size:10px; font-weight:800; color:#94a3b8; margin-bottom:10px;">CONTROLS</div>{render_items(lib_data['controls'])}</div>
                <div><div style="font-size:10px; font-weight:800; color:#94a3b8; margin-bottom:10px;">POLICIES & PROCEDURES</div>{render_items(lib_data['policies'])}</div>
            </div>
        </div>
    </div>
    """
    return html_template

# ---------------------------------------------------------------------------
# 4. STREAMLIT APP
# ---------------------------------------------------------------------------
def run_app():
    st.set_page_config(page_title="Reg Engagement", layout="wide")
    
    if "data" not in st.session_state: st.session_state.data = None
    if "tasks" not in st.session_state: st.session_state.tasks = []
    if "status" not in st.session_state: st.session_state.status = "Draft"

    st.markdown("""
    <style>
        .udp-header { background:linear-gradient(135deg,#0d1b2a,#1b263b); color:#fff; padding:20px 24px; border-radius:12px; margin-bottom:20px; }
        .rationale-card { position: relative; margin-left: 45px; border: 1px solid #e1e0d9; border-radius: 8px; padding: 20px; margin-bottom: 25px; background: white; font-family: sans-serif; }
        .card-icon { position: absolute; left: -50px; top: 0; width: 34px; height: 34px; background: #0369a1; color: white; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; }
        .card-line { position: absolute; left: -34px; top: 32px; bottom: -25px; width: 2px; background: #e1e0d9; }
        .task-container { background: #fff; border: 1px solid #e1e0d9; border-radius: 12px; padding: 25px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }
        .avatar { background:#134e4a; color:white; width:30px; height:30px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:11px; font-weight:700; border: 2px solid #fff; }
    </style>
    <div class="udp-header"><h1>Reg Engagement</h1></div>
    """, unsafe_allow_html=True)

    with st.sidebar:
        st.subheader("Control Center")
        api_key = st.text_input("Gemini API Key", type="password")
        model_id = st.text_input("Model ID", value="models/gemini-3.6-flash")
        url = st.text_input("Engagement Letter URL")
        if st.button("Run Extraction", type="primary"):
            res = process_engagement(url, api_key, model_id)
            if res:
                st.session_state.data = res
                st.session_state.tasks = res.get('ai_tasks', [])

    if st.session_state.data:
        d = st.session_state.data
        
        # SYSTEM HEADER
        st.markdown(f"""
        <div style="background:#0d1b2a; padding:15px 25px; border-radius:12px 12px 0 0; display:flex; justify-content:space-between; align-items:center; color:white; font-family:sans-serif;">
            <div>
                <div style="color:#898781; font-size:11px;">{d.get('engagement_id')} &middot; {d.get('process_id')}</div>
                <div style="font-size:19px; font-weight:700;">{d.get('title')}</div>
                <div style="margin-top:5px;"><span style="background:#fef3c7; color:#d97706; padding:3px 15px; border-radius:20px; font-size:11px; font-weight:600;">● {st.session_state.status}</span></div>
            </div>
            <div style="display:flex; gap:10px;">
                <button style="background:#fff; border:1px solid #ddd; padding:8px 20px; border-radius:6px; font-weight:600; font-size:13px; color:#334155;">Save draft</button>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        col_s1, col_s2 = st.columns([6.3, 1])
        with col_s2:
            st.markdown("<div style='margin-top:-63px;'>", unsafe_allow_html=True)
            if st.button("Submit", type="primary"):
                st.session_state.status = "Open"
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        tab_feed, tab_details, tab_tasks = st.tabs(["💬 Decision feeds", "📋 Engagement Details", "✅ Tasks"])

        with tab_details:
            # Classification
            st.markdown('<div style="font-size:14px; font-weight:700; margin-bottom:10px;">Themes & Domain</div>', unsafe_allow_html=True)
            col_cl1, col_cl2 = st.columns(2)
            with col_cl1: st.multiselect("Risk Themes", THEMES_LIST, default=[t for t in d.get('themes', []) if t in THEMES_LIST])
            with col_cl2: st.multiselect("Business Domain", DOMAINS_LIST, default=[dom for dom in d.get('domain', []) if dom in DOMAINS_LIST])
            
            # Dates
            st.markdown('<div style="font-size:14px; font-weight:700; margin-top:20px; margin-bottom:10px;">Date Fields</div>', unsafe_allow_html=True)
            col_dt1, col_dt2 = st.columns(2)
            with col_dt1: st.date_input("Internal deadline *", value=safe_date_parse(d.get('internal_deadline')))
            with col_dt2: st.date_input("Submission deadline *", value=safe_date_parse(d.get('submission_deadline')))
            
            # Ownership
            st.markdown('<div style="font-size:14px; font-weight:700; margin-top:20px; margin-bottom:10px;">Ownership & Status</div>', unsafe_allow_html=True)
            col_os1, col_os2 = st.columns(2)
            with col_os1:
                st.markdown("""<div style="background:#f8fafc; border:1px solid #e1e0d9; padding:10px; border-radius:4px; display:flex; align-items:center; gap:12px; font-family:sans-serif;">
                    <div style="background:#134e4a; color:white; width:34px; height:34px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:700;">JD</div>
                    <div><div style="font-size:12.5px; font-weight:700;">John Doe 🔒</div><div style="font-size:10.5px; color:#64748b;">Regulatory Affairs</div></div>
                </div>""", unsafe_allow_html=True)
            with col_os2:
                st.session_state.status = st.selectbox("Process Status", STATUS_OPTIONS, index=STATUS_OPTIONS.index(st.session_state.status))

            components.html(_get_dashboard_html(d), height=850, scrolling=True)

        with tab_tasks:
            st.markdown('<div style="font-size:18px; font-weight:800; margin-bottom:20px; color:#0d1b2a;">Task Roadmap</div>', unsafe_allow_html=True)
            st.markdown("<div class='task-container'>", unsafe_allow_html=True)
            for i, task in enumerate(st.session_state.tasks, start=1):
                stat = task.get('status', 'Not Started')
                with st.expander(f"Task {i}: {task.get('title','Action Item')}"):
                    c_t1, c_t2 = st.columns(2)
                    task['status'] = c_t1.selectbox(f"Status - T{i}", TASK_STATUS_OPTIONS, index=TASK_STATUS_OPTIONS.index(stat), key=f"s_{i}")
                    task['date'] = c_t2.date_input(f"Task Deadline Date - T{i}", value=safe_date_parse(task.get('date')), key=f"d_{i}").isoformat()
                    task['desc'] = st.text_area(f"Description", value=task.get('desc',''), key=f"de_{i}")
                    st.text_area("Audit Notes", placeholder="Add updates...", key=f"co_{i}")
                    st.markdown(f'<div style="display:flex; justify-content:flex-end; align-items:center; gap:10px; margin-top:10px;"><span style="font-size:11px; color:#666;">Owner: {task.get("owner")}</span><div class="avatar">{task.get("initials")}</div></div>', unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

            if st.button("＋ Add Operational Task"):
                st.session_state.tasks.append({"title": "Manual Action Item", "status": "Not Started", "date": date.today().isoformat(), "owner": "John Doe", "initials": "JD", "desc": ""})
                st.rerun()

        with tab_feed:
            rationale_steps = [
                ("📄", "Strategic Description", d.get('description', 'N/A')),
                ("🎯", "Scope of Engagement", d.get('scope', 'N/A')),
                ("📈", "Impact", d.get('impact', 'N/A'))
            ]
            for icon, label, text in rationale_steps:
                st.markdown(f"""<div class="rationale-card"><div class="card-icon">{icon}</div><div class="card-line"></div>
                    <div style="font-size:11px; color:#64748b;">John Doe &middot; Updated Today</div>
                    <div style="font-weight:700; color:#0d1b2a; font-size:13px; margin-bottom:5px;">{label}</div>
                    <div style="font-size:13px; color:#334155; line-height:1.6; border:1px solid #f1f5f9; padding:15px; background:#fcfcfb;">{text}</div>
                </div>""", unsafe_allow_html=True)
    else:
        st.info("System Ready. Enter a Regulatory URL and Gemini API Key in the sidebar.")

if __name__ == "__main__":
    run_app()