import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "new"))
sys.path.insert(0, str(ROOT / "new-plugins"))
from connectivity_supervisor import ConnectivitySupervisorPlugin  # noqa: E402


class FakePlugin(ConnectivitySupervisorPlugin):
    def __init__(self, responses):
        self.responses = responses
        self.config = {"ap_iface": "wlan1"}

    def _cfg(self, key):
        return self.config.get(key, self.DEFAULTS.get(key))

    def _sh(self, command, timeout=25):
        return self.responses.get(command, "")


def test_reads_radio_registration_and_lte_signal():
    plugin = FakePlugin({
        "getprop gsm.network.type 2>/dev/null": "LTE",
        "getprop gsm.data.network.type 2>/dev/null": "LTE",
        "getprop gsm.operator.alpha 2>/dev/null": "Claro",
        "dumpsys telephony.registry 2>/dev/null": (
            "mDataRegState=0(IN_SERVICE) "
            "CellSignalStrengthLte: rssi=-85 rsrp=-109 rsrq=-12 rssnr=20 "
            "isNrAvailable=true isEnDcAvailable=true"
        ),
    })

    result = plugin._read_radio()

    assert result["network_type"] == "LTE"
    assert result["operator"] == "Claro"
    assert result["data_registered"] is True
    assert result["data_reg_state"] == "IN_SERVICE"
    assert result["lte_rsrp"] == -109
    assert result["lte_rsrq"] == -12
    assert result["lte_rssnr"] == 20
    assert result["nr_available"] is True
    assert result["endc_available"] is True


def test_reads_tethering_bpf_and_conntrack_errors_without_guessing():
    plugin = FakePlugin({
        "dumpsys tethering 2>/dev/null": (
            "wlan1 - TetheredState\n"
            "mIsBpfEnabled=true\n"
            "Offload HALs started\n"
            "Failed to update conntrack entry: ENOENT\n"
        ),
    })

    result = plugin._read_tethering()

    assert result["active"] is True
    assert result["bpf_enabled"] is True
    assert result["hardware_offload"] is True
    assert result["conntrack_error_count"] == 1
    assert result["conntrack_error_codes"] == ["ENOENT"]


def test_rejects_stale_multiline_shell_output_as_radio_props():
    plugin = FakePlugin({
        "getprop gsm.network.type 2>/dev/null": "Current Battery Service state:\nlevel: 0",
        "getprop gsm.data.network.type 2>/dev/null": "Current Battery Service state:\nlevel: 0",
        "getprop gsm.operator.alpha 2>/dev/null": "Current Battery Service state:\nlevel: 0",
        "dumpsys telephony.registry 2>/dev/null": "Current Battery Service state:\nlevel: 0",
    })

    result = plugin._read_radio()

    assert result["network_type"] == ""
    assert result["data_network_type"] == ""
    assert result["operator"] == ""
    assert result["data_registered"] is None
    assert result["lte_rsrp"] is None


def test_marks_unrecognized_tethering_output_unavailable():
    plugin = FakePlugin({
        "dumpsys tethering 2>/dev/null": "Current Battery Service state:\nlevel: 0",
    })

    result = plugin._read_tethering()

    assert result["available"] is False
    assert result["active"] is None
    assert result["conntrack_error_count"] is None
