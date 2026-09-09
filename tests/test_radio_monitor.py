from xio.radio_monitor import (
    classify_delta,
    flatten_snapshot,
    parse_adapter_stats,
    parse_ping_output,
    parse_telephony_registry,
    parse_wifi_interfaces,
)


TELEPHONY = """
  Phone Id=0
    mServiceState={mVoiceRegState=0(IN_SERVICE), mDataRegState=0(IN_SERVICE), mChannelNumber=9610, mCellBandwidths=[10000], mOperatorAlphaLong=Claro, isManualNetworkSelection=true(manual), getRilVoiceRadioTechnology=14(LTE), getRilDataRadioTechnology=14(LTE), isUsingCarrierAggregation=false, mNetworkRegistrationInfos=[NetworkRegistrationInfo{dataSpecificInfo=android.telephony.DataSpecificRegistrationInfo :{ isNrAvailable = false isEnDcAvailable = false }}], mNrFrequencyRange=0, mIsDataRoamingFromRegistration=false}
    mVoiceActivationState= 0
    mSignalStrength=SignalStrength:{mLte=CellSignalStrengthLte: rssi=-73 rsrp=-103 rsrq=-14 rssnr=-1,mNr=CellSignalStrengthNr:{ csiRsrp = 2147483647 csiRsrq = 2147483647 ssRsrp = 2147483647 ssRsrq = 2147483647 ssSinr = 2147483647 }}
    mMessageWaiting=false
    mPhysicalChannelConfigs=[{mCellBandwidthDownlinkKhz=10000,mPhysicalCellId=326}]
    mLinkCapacityEstimateList=[{mDownlinkCapacityKbps=7612,mUplinkCapacityKbps=236}]
  Phone Id=1
    mServiceState={mChannelNumber=0}
"""


WIFI = """
    SSID                   : XIO
    AP BSSID               : 86:b7:37:f2:db:8b
    Banda                  : 5 GHz
    Canal: 56
    Tipo de radio          : 802.11ac
    Velocidad de recepción (Mbps)   : 468
    Velocidad de transmisión (Mbps) : 780
    Señal                           : 83%
    Rssi           : -57
"""


def test_parse_telephony_uses_active_phone_and_not_history():
    result = parse_telephony_registry(TELEPHONY)
    assert result["operator"] == "Claro"
    assert result["data_rat"] == "LTE"
    assert result["channel"] == 9610
    assert result["bandwidths_mhz"] == [10.0]
    assert result["lte_rsrp_dbm"] == -103
    assert result["physical_cell_id"] == 326
    assert result["is_nr_registered"] is False


def test_parse_wifi_supports_current_spanish_netsh_output():
    result = parse_wifi_interfaces(WIFI)
    assert result == {
        "ssid": "XIO",
        "bssid": "86:b7:37:f2:db:8b",
        "band": "5 GHz",
        "channel": 56,
        "radio_type": "802.11ac",
        "signal_percent": 83,
        "rssi_dbm": -57,
        "receive_mbps": 468.0,
        "transmit_mbps": 780.0,
    }


def test_parse_ping_and_adapters():
    ping = parse_ping_output("Paquetes: enviados = 4, recibidos = 4, perdidos = 0 (0% perdidos),\nMedia = 3ms")
    assert ping == {"packet_loss_percent": 0, "rtt_avg_ms": 3, "reachable": True}
    adapters = parse_adapter_stats('[{"Name":"Wi-Fi","ReceivedBytes":100,"SentBytes":50}]')
    assert adapters == [{"name": "Wi-Fi", "received_bytes": 100, "sent_bytes": 50}]


def test_delta_marks_radio_and_hotspot_changes_without_claiming_throttling():
    old = {"cellular": {"data_rat": "LTE", "channel": 9610, "operator": "Claro", "physical_cell_id": 326, "bandwidths_khz": [10000], "carrier_aggregation": False, "lte_rsrp_dbm": -103}, "wifi": {"bssid": "a", "channel": 36, "band": "5 GHz", "rssi_dbm": -57}}
    new = {"cellular": {"data_rat": "NR", "channel": 640000, "operator": "Claro", "physical_cell_id": 326, "bandwidths_khz": [100000], "carrier_aggregation": True, "lte_rsrp_dbm": -94}, "wifi": {"bssid": "b", "channel": 56, "band": "5 GHz", "rssi_dbm": -70}}
    events = classify_delta(old, new)
    assert "cell_identity_or_rat_changed" in events
    assert "cell_aggregation_changed" in events
    assert "hotspot_wifi_identity_changed" in events
    assert "cell_signal_step_changed" in events
    assert "hotspot_wifi_signal_step_changed" in events
    assert "throttling" not in "+".join(events)


def test_flatten_preserves_serializable_bandwidths_and_rates():
    snapshot = {
        "timestamp_utc": "2026-08-27T18:00:10+00:00",
        "cellular": {"operator": "Claro", "data_rat": "LTE", "bandwidths_mhz": [10.0], "carrier_aggregation": False},
        "wifi": {},
        "paths": {"gateway": {}, "internet": {}},
        "adapters": [{"name": "Wi-Fi", "received_bytes": 130, "sent_bytes": 90}],
    }
    previous = {"timestamp_utc": "2026-08-27T18:00:00+00:00", "adapters": [{"name": "Wi-Fi", "received_bytes": 100, "sent_bytes": 50}]}
    row = flatten_snapshot(snapshot, "sample", previous)
    assert row["cell_bandwidths_mhz"] == "[10.0]"
    assert '"Wi-Fi"' in row["adapter_rates"]
