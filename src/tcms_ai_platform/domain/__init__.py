"""领域知识层：把挖掘出的真实领域知识(源码/标准/概念)注入图谱与向量库。"""

from .enrichment import (
    enrich_graph,
    inject_ebm,
    inject_network,
    inject_safety,
    load_domain_json,
)

__all__ = ["enrich_graph", "inject_ebm", "inject_network", "inject_safety", "load_domain_json"]
