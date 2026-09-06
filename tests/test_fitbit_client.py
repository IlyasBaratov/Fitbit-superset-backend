from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app.providers.fitbit.client import FitbitClient

@pytest.mark.parametrize("method,args,suffix", [
    ("profile", [], "/1/user/-/profile.json"),
    ("intraday", ["heart", "2026-08-20", "1sec"], "/1/user/-/activities/heart/date/2026-08-20/1d/1sec.json"),
    ("sleep", ["2026-08-01", "2026-08-20"], "/1.2/user/-/sleep/date/2026-08-01/2026-08-20.json"),
    ("spo2_intraday", ["2026-08-01", "2026-08-20"], "/1/user/-/spo2/date/2026-08-01/2026-08-20/all.json"),
])
def test_fitbit_endpoint_contract(method, args, suffix):
    transport = Mock()
    client = FitbitClient(SimpleNamespace(fitbit_api_base_url="https://api.fitbit.com"), transport)
    getattr(client, method)(*args)
    transport.request.assert_called_once_with("https://api.fitbit.com" + suffix)


def test_tcx_keeps_xml_response():
    transport = Mock()
    client = FitbitClient(SimpleNamespace(fitbit_api_base_url="https://api.fitbit.com"), transport)
    assert client.tcx("https://api.fitbit.com/workout.tcx") is transport.request.return_value
