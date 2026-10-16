"""Chain schema and synthetic fixture tests. No provider is called."""

from datetime import datetime, timedelta

from app.options.fixtures import FIXTURE_ORIGIN, synthetic_nifty_chain
from app.options.schema import parse_option_chain
from app.options.validation import validate_option_chain


def _codes(result: dict) -> set[str]:
    return {item["code"] for item in result["errors"]}


def test_synthetic_chain_is_deterministic_and_labelled():
    first = synthetic_nifty_chain()
    second = synthetic_nifty_chain()
    assert first == second
    first["contracts"][0]["bid"] = 1
    assert synthetic_nifty_chain()["contracts"][0]["bid"] == 180.0
    chain = synthetic_nifty_chain()
    assert chain["origin"] == FIXTURE_ORIGIN
    assert chain["label"] == FIXTURE_ORIGIN
    assert chain["market_observation"] is False
    assert chain["real_market_data_verified"] is False
    assert chain["trading_symbol"] is None
    assert chain["lot_size"] is None
    assert "exchange" not in chain
    strikes = {row["strike"] for row in chain["contracts"]}
    kinds = {row["option_type"] for row in chain["contracts"]}
    assert strikes == {25000, 25100, 25200}
    assert kinds == {"CE", "PE"}
    assert all(row["origin"] == FIXTURE_ORIGIN for row in chain["contracts"])
    assert all(row["greeks"]["delta"] is None for row in chain["contracts"])


def test_valid_chain_has_no_expected_net_and_no_trade():
    chain = synthetic_nifty_chain()
    chain["forecast"] = {"p_up": 0.9, "p_down": 0.1}
    report = validate_option_chain(chain)
    assert report["ok"] is True
    assert report["pricing"]["status"] == "UNAVAILABLE"
    assert report["pricing"]["method"] is None
    assert report["pricing"]["premium"] is None
    assert report["pricing"]["expected_net"] is None
    assert report["decision"] == "NO_TRADE"
    assert report["decision_reason"] == "NO_APPROVED_FORECAST"
    assert report["forecast_accepted"] is False
    assert report["forecast_ready"] is False
    assert report["paper_approved"] is False
    assert report["live_approved"] is False
    assert report["real_market_data_verified"] is False
    assert report["snapshot"]["expected_net"] is None
    assert all(row["accepted"]["premium"] is None for row in report["contracts"])
    assert all(row["accepted"]["greeks"]["theta"] is None for row in report["contracts"])
    snapshot, parsed = parse_option_chain(synthetic_nifty_chain())
    assert snapshot is not None
    assert parsed["ok"] is True
    assert snapshot.decision == "NO_TRADE"
    assert snapshot.pricing_status == "UNAVAILABLE"
    assert len(snapshot.contracts) == 6


def test_invalid_quotes_expiry_and_option_type_fail_closed():
    crossed = synthetic_nifty_chain()
    crossed["contracts"][0]["bid"] = 200
    crossed["contracts"][0]["ask"] = 100
    assert "INVALID_SPREAD" in _codes(validate_option_chain(crossed))
    negative = synthetic_nifty_chain()
    negative["contracts"][1]["ask"] = -1
    assert "INVALID_ASK" in _codes(validate_option_chain(negative))
    expiry = synthetic_nifty_chain()
    expiry["expiry"] = "Thursday"
    for row in expiry["contracts"]:
        row["expiry"] = "Thursday"
    assert "INVALID_EXPIRY" in _codes(validate_option_chain(expiry))
    kind = synthetic_nifty_chain()
    kind["contracts"][2]["option_type"] = "SHORT_CE"
    assert "INVALID_OPTION_TYPE" in _codes(validate_option_chain(kind))
    assert validate_option_chain(kind)["decision"] == "NO_TRADE"
    assert validate_option_chain(kind)["pricing"]["expected_net"] is None


def test_missing_and_naive_timestamps_and_stale_quotes():
    missing = synthetic_nifty_chain()
    missing["quote_timestamp"] = None
    for row in missing["contracts"]:
        row["quote_timestamp"] = None
    assert "INVALID_QUOTE_TIME" in _codes(validate_option_chain(missing))
    naive = synthetic_nifty_chain()
    naive["quote_timestamp"] = "2026-10-14T10:00:00"
    for row in naive["contracts"]:
        row["quote_timestamp"] = "2026-10-14T10:00:00"
    assert "INVALID_QUOTE_TIME" in _codes(validate_option_chain(naive))
    retrieved = synthetic_nifty_chain()
    retrieved["retrieved_at"] = "2026-10-14T10:00:01"
    assert "INVALID_RETRIEVED_AT" in _codes(validate_option_chain(retrieved))
    stale = validate_option_chain(
        synthetic_nifty_chain(),
        as_of=datetime.fromisoformat("2026-10-14T10:00:00+05:30") + timedelta(seconds=16),
    )
    assert "STALE_QUOTE" in _codes(stale)
    assert stale["snapshot"] is None


def test_mixed_provenance_and_calculated_quotes_are_rejected():
    mixed = synthetic_nifty_chain()
    mixed["contracts"][0]["origin"] = "UNVERIFIED_MARKET_INPUT"
    assert "MIXED_PROVENANCE" in _codes(validate_option_chain(mixed))
    calculated = synthetic_nifty_chain()
    calculated["contracts"][3]["origin"] = "CALCULATED"
    report = validate_option_chain(calculated)
    assert "CALCULATED_NOT_A_QUOTE" in _codes(report)
    assert "MIXED_PROVENANCE" in _codes(report)
    assert report["pricing"]["expected_net"] is None
    whole = synthetic_nifty_chain()
    whole["origin"] = "CALCULATED"
    for row in whole["contracts"]:
        row["origin"] = "CALCULATED"
    assert "CALCULATED_NOT_A_QUOTE" in _codes(validate_option_chain(whole))


def test_empty_and_malformed_chains_do_not_price():
    empty = synthetic_nifty_chain()
    empty["contracts"] = []
    empty_report = validate_option_chain(empty)
    assert "EMPTY_CHAIN" in _codes(empty_report)
    assert empty_report["snapshot"] is None
    assert empty_report["decision"] == "NO_TRADE"
    malformed = validate_option_chain({"origin": "SYNTHETIC_FIXTURE", "contracts": "no"})
    assert "INVALID_CHAIN" in _codes(malformed)
    broken = synthetic_nifty_chain()
    broken["contracts"][0] = "not-a-contract"
    assert "INVALID_PAYLOAD" in _codes(validate_option_chain(broken))
    inconsistent = synthetic_nifty_chain()
    inconsistent["contracts"][4]["expiry"] = "2026-10-27"
    assert "INCONSISTENT_CHAIN" in _codes(validate_option_chain(inconsistent))
    assert parse_option_chain(empty)[0] is None
