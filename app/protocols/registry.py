"""Maps a protocol name to its adapter. The one place you touch to add a
fourth protocol (Visa TAP, Mastercard Agent Pay, ...)."""
from __future__ import annotations

from app.protocols.ap2_adapter import AP2Adapter
from app.protocols.acp_adapter import ACPAdapter
from app.protocols.base import ProtocolAdapter
from app.protocols.upi_agentic_adapter import UPIAgenticAdapter
from app.schemas import SourceProtocol

_ADAPTERS: dict[SourceProtocol, ProtocolAdapter] = {
    SourceProtocol.AP2: AP2Adapter(),
    SourceProtocol.ACP: ACPAdapter(),
    SourceProtocol.UPI_AGENTIC: UPIAgenticAdapter(),
}


def get_adapter(protocol: SourceProtocol) -> ProtocolAdapter:
    try:
        return _ADAPTERS[protocol]
    except KeyError as exc:
        raise ValueError(f"No adapter registered for protocol '{protocol}'") from exc
