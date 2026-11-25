from types import SimpleNamespace

import pytest

from marine_evidence.answer import AnswerError, call_openai
from marine_evidence.agent import call_agent_planner


@pytest.mark.parametrize('stage,budget', [('Generator', 8192), ('Agent', 4096)])
@pytest.mark.parametrize('reason', ['max_output_tokens', 'content_filter', None])
def test_incomplete_response_reports_stage_and_reason(stage, budget, reason):
    class FakeResponses:
        def create(self, **kwargs):
            assert kwargs['max_output_tokens'] == budget
            assert kwargs['store'] is False
            return SimpleNamespace(
                status='incomplete',
                incomplete_details=SimpleNamespace(reason=reason) if reason else None,
                usage=SimpleNamespace(output_tokens=budget),
                output_text='{"partial": true}',
            )
    client = SimpleNamespace(responses=FakeResponses())
    with pytest.raises(AnswerError) as exc:
        if stage == 'Generator':
            call_openai('What happened?', [], model='test-model', client=client)
        else:
            call_agent_planner('What happened?', {}, model='test-model', client=client)
    message = str(exc.value)
    assert stage in message and 'incomplete' in message
    assert f'reason={reason or "unknown"}' in message
    assert f'output_tokens={budget}' in message
    assert f'max_output_tokens={budget}' in message
