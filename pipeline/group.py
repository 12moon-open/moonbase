"""Group source rows, one per stream, into stations.

Two rows are one station when they share a stream, or when they have the same
name in the same country and either the same channel in their path, or a domain
that is not shared hosting and compatible channels (one empty, or one the start
of the other). The domain rule is not used for a row whose stream also carries
another name: such a row may be mislabelled.

A row with no country is compared with the rows of the only country that has its
name, if there is exactly one.

A name alone is never enough: source rows are sometimes mislabelled, and a
duplicate record does less harm than a wrong stream in a record.
"""
from collections import defaultdict

from .normalize import registrable_domain, stream_channel

MAX_STREAMS_BY_NAME = 12  # Above this, a "name" is a label used by many stations.
SHARED_DOMAIN_NAMES = 100  # A domain used by more names than this is shared hosting.


class _Sets:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, i):
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parent[max(a, b)] = min(a, b)


def _signals(row):
    urls = [row["stream"]] + ([row["homepage"]] if row.get("homepage") else [])
    return {d for d in map(registrable_domain, urls) if d}


def _compatible(a, b):
    """Channels that may name one station: fip and fiphd, or an unnamed path."""
    return not a or not b or a.startswith(b) or b.startswith(a)


def shared_domains(rows):
    """Domains used by more than SHARED_DOMAIN_NAMES names: shared hosting, not a station's own."""
    names_by_domain = defaultdict(set)
    for row in rows:
        for domain in _signals(row):
            names_by_domain[domain].add(row["name_key"])
    return {d for d, names in names_by_domain.items() if len(names) > SHARED_DOMAIN_NAMES}


def group_rows(rows):
    """Return lists of rows. Each row has stream, stream_key, name_key, country."""
    sets = _Sets(len(rows))
    by_stream = {}
    for i, row in enumerate(rows):
        sets.union(i, by_stream.setdefault(row["stream_key"], i))

    shared = shared_domains(rows)

    countries_by_name = defaultdict(set)
    for row in rows:
        if row["name_key"] and row["country"]:
            countries_by_name[row["name_key"]].add(row["country"])

    buckets = defaultdict(list)
    for i, row in enumerate(rows):
        if not row["name_key"]:
            continue
        country = row["country"]
        if not country and len(countries_by_name[row["name_key"]]) == 1:
            country = next(iter(countries_by_name[row["name_key"]]))
        buckets[(country, row["name_key"])].append(i)
    names_by_stream = defaultdict(set)
    for row in rows:
        names_by_stream[row["stream_key"]].add(row["name_key"])

    for members in buckets.values():
        if len({rows[i]["stream_key"] for i in members}) > MAX_STREAMS_BY_NAME:
            continue
        by_channel, by_domain = {}, defaultdict(list)
        for i in members:
            channel = stream_channel(rows[i]["stream"])
            if channel:
                sets.union(i, by_channel.setdefault(channel, i))
            if len(names_by_stream[rows[i]["stream_key"]]) > 1:
                continue
            for domain in sorted(_signals(rows[i]) - shared):
                for j, other in by_domain[domain]:
                    if _compatible(channel, other):
                        sets.union(i, j)
                by_domain[domain].append((i, channel))

    groups = defaultdict(list)
    for i, row in enumerate(rows):
        groups[sets.find(i)].append(row)
    return list(groups.values())
