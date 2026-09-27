import json
from urllib.parse import quote
import pytest
from runtime.media_missher_runtime.contracts import Target, ContractError
from runtime.media_missher_runtime.models import CollectionRequest
from runtime.media_missher_runtime.platforms import x


def response_url(variables):
    return 'https://x.com/i/api/graphql/fixture/SearchTimeline?variables='+quote(json.dumps(variables))


def test_handle_is_normalized_and_length_matches_homepage():
    assert Target(platform='x',mode='creator',handle='@Somebody').identity=='x:creator:somebody'
    assert Target(platform='x',mode='creator',homepage='https://twitter.com/Somebody').handle=='somebody'
    with pytest.raises(ContractError):Target(platform='x',mode='creator',handle='a'*16)


def test_search_sort_reaches_collector_and_response_binding():
    request=CollectionRequest(platform='x',keyword='中文 AI',count=1,sort='top')
    target=x.XCollector(request,object())._target()
    assert target.sort=='top' and 'f=top' in x.target_url(target)
    bound=x.target_binding(target)
    assert x.response_matches(url=response_url({'rawQuery':'中文 AI','product':'Top'}),binding=bound)
    for value in [
        {'rawQuery':'中文 AI','product':'Latest'},
        {'rawQuery':'中文 AI'},
        {'nested':{'rawQuery':'中文 AI'},'product':'Top'},
        {'rawQuery':'中文 ai','product':'Top'},
    ]:
        assert not x.response_matches(url=response_url(value),binding=bound)


def test_duplicate_variable_keys_and_non_object_variables_are_refused():
    bound=x.target_binding(Target(platform='x',mode='search',keyword='ai',sort='latest'))
    for raw in ['{"rawQuery":"other","rawQuery":"ai","product":"Latest"}', '[{"rawQuery":"ai"}]']:
        url='https://x.com/i/api/graphql/fixture/SearchTimeline?variables='+quote(raw)
        assert not x.response_matches(url=url,binding=bound)
