"""dropscope: real-time drop attribution for AI/RoCEv2 fabrics in SONiC."""

from .models import (
    ROCEV2_UDP_PORT,
    AttributedDrop,
    DropEvent,
    DropReason,
    EndpointRole,
)
from .registry import Job, JobRegistry
from .correlate import Correlator
from .aggregate import Aggregator

__all__ = [
    "ROCEV2_UDP_PORT",
    "AttributedDrop",
    "DropEvent",
    "DropReason",
    "EndpointRole",
    "Job",
    "JobRegistry",
    "Correlator",
    "Aggregator",
]

__version__ = "0.1.0"
