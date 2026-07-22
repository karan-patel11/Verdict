"""Memory graph — the per-file analysis graph generated when a file's analysis completes.

`schema` defines the typed, closed contract; `builder` derives findings and assembles the
graph from real analyzed-field outcomes; `validator` refuses malformed graphs before they
are persisted. Layout and rendering live in the front-end and never leak back here.
"""
from .builder import FieldOutcome, Finding, METRIC_INPUTS, build_file_graph, derive_findings
from .schema import (
    AnalysisStatus,
    CATEGORY_RANK,
    EdgeRelation,
    GRAPH_SCHEMA_VERSION,
    GraphEdge,
    GraphMetadata,
    GraphNode,
    MemoryGraph,
    NodeCategory,
    NodeStatus,
    Severity,
    SourceRef,
    severity_rank,
    worst_severity,
)
from .validator import GraphValidationError, RELATION_ENDPOINTS, assert_valid, validate_graph

__all__ = [
    "AnalysisStatus", "CATEGORY_RANK", "EdgeRelation", "FieldOutcome", "Finding",
    "GRAPH_SCHEMA_VERSION", "GraphEdge", "GraphMetadata", "GraphNode", "GraphValidationError",
    "METRIC_INPUTS", "MemoryGraph", "NodeCategory", "NodeStatus", "RELATION_ENDPOINTS",
    "Severity", "SourceRef", "assert_valid", "build_file_graph", "derive_findings",
    "severity_rank", "validate_graph", "worst_severity",
]
