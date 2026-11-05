"""Marine Evidence Finder UI. Start FastAPI first; then `streamlit run streamlit_app.py`."""
from __future__ import annotations

import os
from urllib.parse import quote

import requests
import streamlit as st

st.set_page_config(page_title='Marine Evidence Finder', page_icon='🐋', layout='wide')
API_URL = os.environ.get('MARINE_API_URL', 'http://127.0.0.1:8000').rstrip('/')


def api_request(method: str, path: str, **kwargs):
    response = requests.request(method, API_URL + path, timeout=kwargs.pop('timeout', 25), **kwargs)
    if not response.ok:
        try:
            details = response.json().get('detail', response.text)
        except ValueError:
            details = response.text
        raise RuntimeError(f'API HTTP {response.status_code}: {details}')
    return response.json()


def pdf_link(source_id: str, page: int = 1) -> str:
    return f'{API_URL}/documents/{quote(source_id, safe="")}/pdf#page={int(page)}'


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
    if st.button('Add PDF to search', disabled=uploaded_file is None, use_container_width=True):
        try:
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
        mode = st.radio('Mode', ['Search passages (free)', 'Generate cited answer (OpenAI API)'],
                        horizontal=False)
    with col2:
        top_k = st.slider('Top-k passages', min_value=1, max_value=15, value=5)
        distinct_pages = st.checkbox('One passage per page', value=False)
    with col3:
        model = st.text_input('OpenAI model', value='gpt-5-mini',
                              disabled=(mode == 'Search passages (free)'))
    submitted = st.form_submit_button('Search' if mode.startswith('Search') else 'Generate answer',
                                       type='primary', use_container_width=True)

if submitted:
    if not question.strip():
        st.warning('Enter a research question first.')
    else:
        payload = {'question': question.strip(), 'top_k': top_k, 'distinct_pages': distinct_pages}
        if mode.startswith('Generate'):
            payload['model'] = model.strip() or 'gpt-5-mini'
        try:
            with st.spinner('Searching PDF evidence...' if mode.startswith('Search') else 'Searching and calling the OpenAI API...'):
                output = api_request('POST', '/search' if mode.startswith('Search') else '/ask',
                                     json=payload, timeout=150)
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
        if output['status'] == 'insufficient_evidence':
            st.warning('Insufficient evidence in the retrieved passages')
            st.write(output['reason'])
        else:
            citation_map = {c['chunk_id']: c for c in output['citations']}
            for claim in output['claims']:
                st.write(claim['statement'])
                links = []
                for cid in claim['citation_ids']:
                    c = citation_map[cid]
                    links.append(f"[{c['source_id']} p.{c['pdf_page']}]({pdf_link(c['source_id'], c['pdf_page'])})")
                st.markdown('Sources: ' + ' · '.join(links))
        st.info('Source IDs and PDF pages are checked. Scientific entailment is NOT automatically verified.')
        st.caption(f"Model: {output['model']} · Retrieved {len(output['retrieved'])} passages")
        with st.expander('Retrieval trace'):
            for hit in output['retrieved']:
                st.markdown(f"**#{hit['rank']}** — [{hit['source_id']} PDF p.{hit['pdf_page']}]({pdf_link(hit['source_id'], hit['pdf_page'])}) — BM25 {hit['score']:.2f} · `{hit['chunk_id']}`")

st.divider()
st.caption('Local MVP · PDFs are stored on this computer. Only the question and top retrieved passages are sent to the LLM when you explicitly choose Generate.')
