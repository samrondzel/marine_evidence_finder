"""Marine Evidence Finder UI. Start FastAPI first; then `streamlit run streamlit_app.py`."""
from __future__ import annotations

import os

import requests
import streamlit as st

from marine_evidence.ui_urls import pdf_link

st.set_page_config(page_title='Marine Evidence Finder', page_icon='🐋', layout='wide')
API_URL = os.environ.get('MARINE_API_URL', 'http://127.0.0.1:8000').rstrip('/')
ASYNC_INGESTION = os.environ.get('MARINE_ASYNC_INGESTION') == '1'


def api_request(method: str, path: str, **kwargs):
    response = requests.request(method, API_URL + path, timeout=kwargs.pop('timeout', 25), **kwargs)
    if not response.ok:
        try:
            details = response.json().get('detail', response.text)
        except ValueError:
            details = response.text
        raise RuntimeError(f'API HTTP {response.status_code}: {details}')
    return response.json()


st.title('🐋 Marine Evidence Finder')
st.caption('Search scientific PDFs. Get grounded answers with links to the original pages.')

try:
    health = api_request('GET', '/health', timeout=8)
    documents = api_request('GET', '/documents', timeout=8)['documents']
except (requests.RequestException, RuntimeError, KeyError) as exc:
    st.error(f'API unavailable: {exc}')
    st.info('Start the API in another terminal: `python -m uvicorn marine_evidence.api:app --host 127.0.0.1 --port 8000`')
    st.stop()

with st.sidebar:
    st.subheader('Collection')
    st.metric('PDFs', health['documents'])
    st.metric('Search chunks', health['chunks'])
    st.caption('BM25 (the strongest retriever on our current development benchmark)')
    st.divider()
    st.subheader('Upload a PDF')
    uploaded_file = st.file_uploader('Text-based PDF (25 MiB max, 100 pages max)', type=['pdf'])
    pending_job = st.session_state.get('pending_ingestion_job_id')
    if st.button('Add PDF to search', disabled=uploaded_file is None or pending_job is not None,
                 use_container_width=True):
        try:
            if ASYNC_INGESTION:
                result = api_request('POST', '/ingestion-jobs', timeout=40,
                                     files={'file': (uploaded_file.name, uploaded_file.getvalue(), 'application/pdf')})
                st.session_state['pending_ingestion_job_id'] = result['job_id']
                st.rerun()
            else:
                with st.spinner('Extracting and indexing PDF...'):
                    result = api_request('POST', '/documents', timeout=180,
                                         files={'file': (uploaded_file.name, uploaded_file.getvalue(), 'application/pdf')})
                st.session_state.pop('last_result', None)
                st.session_state['upload_notice'] = (
                    'This PDF was already indexed.' if result['duplicate'] else
                    f"Indexed {result['document']['pages']} pages and {result['document']['chunks']} chunks."
                )
                st.rerun()
        except (requests.RequestException, RuntimeError, KeyError) as exc:
            st.error(str(exc))
    if ASYNC_INGESTION and pending_job:
        try:
            job = api_request('GET', f'/ingestion-jobs/{pending_job}', timeout=8)
            if job['status'] in ('queued', 'running'):
                st.info(f"Ingestion {job['status']}: {pending_job[:8]}…")
                st.button('Refresh ingestion status', key='refresh_ingestion', use_container_width=True)
            elif job['status'] == 'succeeded':
                st.session_state.pop('pending_ingestion_job_id', None)
                st.session_state.pop('last_result', None)
                st.session_state['upload_notice'] = (
                    'Already indexed.' if job['duplicate'] else f"PDF indexed: {job['source_id']}")
                st.rerun()
            else:
                st.error(f"PDF processing failed: {job.get('error') or 'unknown error'}")
                if st.button('Dismiss failure', use_container_width=True):
                    st.session_state.pop('pending_ingestion_job_id', None)
                    st.rerun()
        except (requests.RequestException, RuntimeError, KeyError) as exc:
            st.error(f'Could not check ingestion status: {exc}')
    if 'upload_notice' in st.session_state:
        st.success(st.session_state.pop('upload_notice'))
    st.divider()
    st.subheader('Sources')
    for doc in documents:
        with st.expander(f"{'📄' if doc['uploaded'] else '📚'} {doc['filename']}"):
            st.write(doc['title'])
            st.caption(f"{doc['source_id']} · {doc['pages']} pages · {doc['chunks']} chunks")
            st.markdown(f"[Open PDF]({pdf_link(doc['source_id'])})")
            if doc['uploaded']:
                confirm_key = f"delete_ok_{doc['source_id']}"
                st.checkbox('Confirm removal', key=confirm_key)
                if st.button('Remove uploaded PDF', key=f"delete_{doc['source_id']}",
                             disabled=not st.session_state[confirm_key]):
                    try:
                        api_request('DELETE', f"/documents/{doc['source_id']}")
                        st.session_state.pop('last_result', None)
                        st.session_state['upload_notice'] = 'Uploaded PDF removed from the index.'
                        st.rerun()
                    except (requests.RequestException, RuntimeError) as exc:
                        st.error(str(exc))

st.subheader('Ask the collection')
with st.form('research_question'):
    question = st.text_area('Research question', placeholder='How does shipping noise affect humpback whale foraging?',
                            height=110)
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        mode = st.radio('Mode', ['Search passages (free)', 'Generate cited answer (OpenAI API)',
                              'Agentic research (OpenAI API)'],
                        horizontal=False)
    with col2:
        top_k = st.slider('Top-k passages', min_value=1, max_value=15, value=5)
        distinct_pages = st.checkbox('One passage per page', value=False)
    with col3:
        model = st.text_input('OpenAI model', value='gpt-5-mini',
                              disabled=(mode == 'Search passages (free)'))
        max_steps = st.slider('Agent max steps', 2, 6, 5,
                              disabled=not mode.startswith('Agentic'))
    submitted = st.form_submit_button('Search' if mode.startswith('Search') else 'Generate answer',
                                       type='primary', use_container_width=True)

if submitted:
    if not question.strip():
        st.warning('Enter a research question first.')
    else:
        payload = {'question': question.strip(), 'top_k': top_k, 'distinct_pages': distinct_pages}
        if not mode.startswith('Search'):
            payload['model'] = model.strip() or 'gpt-5-mini'
        if mode.startswith('Agentic'):
            payload['max_steps'] = max_steps
            payload['top_k'] = min(top_k, 6)
        try:
            with st.spinner('Searching PDF evidence...' if mode.startswith('Search') else 'Searching and calling the OpenAI API...'):
                path = ('/search' if mode.startswith('Search') else
                        '/agent/ask' if mode.startswith('Agentic') else '/ask')
                output = api_request('POST', path, json=payload, timeout=260)
            st.session_state['last_result'] = {'mode': mode, 'data': output, 'question': question.strip()}
        except (requests.RequestException, RuntimeError) as exc:
            st.error(str(exc))

if 'last_result' in st.session_state:
    result = st.session_state['last_result']
    output = result['data']
    st.divider()
    st.caption(f"Question: {result['question']}")
    if result['mode'].startswith('Search'):
        st.subheader('Evidence matches')
        if not output['hits']:
            st.warning('No keyword matches found. BM25 cannot search for unseen synonyms.')
        for hit in output['hits']:
            with st.expander(f"#{hit['rank']} · {hit['source_id']} · PDF p.{hit['pdf_page']} · BM25 {hit['score']:.2f}",
                             expanded=(hit['rank'] == 1)):
                st.write(hit['title'])
                st.markdown(f"[Open source page]({pdf_link(hit['source_id'], hit['pdf_page'])})")
                st.text(hit['text'])
    else:
        st.subheader('Grounded answer')
        citation_map = {c['chunk_id']: c for c in output['citations']}
        if output['status'] == 'partially_answered':
            st.warning('Partially answered — some evidence is missing')
        elif output['status'] == 'insufficient_evidence':
            st.warning('Insufficient evidence in the retrieved passages')
        for claim in output['claims']:
            st.write(claim['statement'])
            links = []
            for cid in claim['citation_ids']:
                c = citation_map[cid]
                links.append(f"[{c['source_id']} p.{c['pdf_page']}]({pdf_link(c['source_id'], c['pdf_page'])})")
            st.markdown('Sources: ' + ' · '.join(links))
        if output['status'] != 'answered':
            st.write(output['reason'])
            refs = [citation_map[cid] for cid in output.get('reason_citation_ids', [])]
            if refs:
                st.markdown('Sources for explanation: ' + ' · '.join(
                    f"[{c['source_id']} p.{c['pdf_page']}]({pdf_link(c['source_id'], c['pdf_page'])})" for c in refs))
        if result['mode'].startswith('Agentic'):
            st.caption(f"Agent: {output['steps']} decisions · {output['tool_calls']} read-only tool calls · stop={output['stop_reason']}")
            with st.expander('Agent tool trace', expanded=True):
                for event in output['trace']:
                    stage = ('Step 0 (automatic original-question search)'
                             if event['step'] == 0 else f"Planner step {event['step']}")
                    st.markdown(f"**{stage}: {event['action']}** — {event['note']}")
                    if 'query' in event:
                        st.code(event['query'], language=None)
                    if 'chunk_id' in event:
                        st.caption('Context around ' + event['chunk_id'])
                    if 'added_chunk_ids' in event:
                        st.caption('New passages: ' + ', '.join(event['added_chunk_ids']))
                    if 'outcome' in event:
                        st.warning('Guardrail: ' + event['outcome'])
        usage = output.get('llm_usage')
        if usage is not None:
            with st.expander('LLM usage and estimated API cost'):
                cost = usage.get('estimated_cost_usd')
                st.metric('Estimated USD', f'${cost:.6f}' if cost is not None else 'Unknown')
                st.write(f"LLM calls: {usage['llm_calls']} · Unpriced: {usage['unpriced_calls']}")
                if cost is None:
                    st.caption(f"Known estimated subtotal: ${usage['known_cost_usd']:.6f}")
                st.json({k: v for k, v in usage.items() if k != 'calls'})
                if usage['calls']:
                    st.dataframe(usage['calls'], use_container_width=True)
                st.caption('Cached input and reasoning tokens are subsets of input and output. Estimate, not a bill; SDK retries may not be visible.')
        st.info('Source IDs and PDF pages are checked. Scientific entailment is NOT automatically verified.')
        st.caption(f"Model: {output['model']} · Retrieved {len(output['retrieved'])} passages")
        with st.expander('Retrieval trace'):
            for hit in output['retrieved']:
                st.markdown(f"**#{hit['rank']}** — [{hit['source_id']} PDF p.{hit['pdf_page']}]({pdf_link(hit['source_id'], hit['pdf_page'])}) — BM25 {hit['score']:.2f} · `{hit['chunk_id']}`")

st.divider()
st.caption('Local MVP · OpenAI modes send the question and bounded PDF evidence to an external LLM only when explicitly selected. Agent mode can make several paid API calls. Never expose this unauthenticated app publicly.')
