"""Organism identity - the single resolver every engine uses.

WHY THIS EXISTS. Organism matching used to be done inline, in a dozen places,
with `key in name or name in key`. That test has three failure modes, all of
which reached reports:

  * an EMPTY organism name is a substring of everything, so with no organism
    selected every drug that is intrinsic for ANY species was banned and every
    organism was "AmpC-prone";
  * a genus-only name ("Proteus") silently unioned the tables of every species
    in the genus;
  * a species the table does not list by that exact spelling ("MRSA",
    "Klebsiella aerogenes") matched nothing, or matched the wrong genus-level
    row (K. aerogenes is an AmpC organism - an Enterobacter in all but name -
    and must not inherit K. pneumoniae's penicillinase-only profile).

`identify()` turns a free-text name into one immutable `Organism` carrying its
canonical key and the group memberships the rules need. Unknown or empty names
resolve to an organism that belongs to NO group, so a rule can never fire by
accident.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import FrozenSet, Iterable, Optional, Tuple

from clinical_data import INTRINSIC_RESISTANCE

# ── canonical spellings ───────────────────────────────────────────────────
_ALIASES = {
    "e. coli": "escherichia coli", "e.coli": "escherichia coli", "e coli": "escherichia coli",
    "k. pneumoniae": "klebsiella pneumoniae", "k. oxytoca": "klebsiella oxytoca",
    "klebsiella": "klebsiella spp.",
    # K. aerogenes was Enterobacter aerogenes until 2017 and behaves like one
    # (chromosomal inducible AmpC). The intrinsic table lists it under the old name.
    "klebsiella aerogenes": "enterobacter aerogenes", "k. aerogenes": "enterobacter aerogenes",
    "e. cloacae": "enterobacter cloacae", "enterobacter cloacae complex": "enterobacter cloacae",
    "enterobacter": "enterobacter spp.",
    "c. freundii": "citrobacter freundii", "c. koseri": "citrobacter koseri",
    "citrobacter diversus": "citrobacter koseri", "citrobacter": "citrobacter spp.",
    "s. marcescens": "serratia marcescens", "serratia": "serratia spp.",
    "p. mirabilis": "proteus mirabilis", "proteus": "proteus spp.",
    "p. vulgaris": "proteus vulgaris", "proteus penneri": "proteus vulgaris",
    "m. morganii": "morganella morganii", "morganella": "morganella morganii",
    "morganella spp.": "morganella morganii",
    "providencia": "providencia spp.", "providencia stuartii": "providencia spp.",
    "providencia rettgeri": "providencia spp.",
    "hafnia": "hafnia alvei",
    "salmonella": "salmonella spp.", "shigella": "shigella spp.",
    "p. aeruginosa": "pseudomonas aeruginosa", "pseudomonas": "pseudomonas aeruginosa",
    "pseudomonas spp.": "pseudomonas aeruginosa",
    "a. baumannii": "acinetobacter baumannii", "acinetobacter": "acinetobacter baumannii",
    "acinetobacter spp.": "acinetobacter baumannii",
    "acinetobacter baumannii complex": "acinetobacter baumannii",
    "s. maltophilia": "stenotrophomonas maltophilia",
    "stenotrophomonas": "stenotrophomonas maltophilia",
    "s. aureus": "staphylococcus aureus", "staph aureus": "staphylococcus aureus",
    "staph. aureus": "staphylococcus aureus",
    "mssa": "staphylococcus aureus", "mrsa": "staphylococcus aureus",
    "cons": "staphylococcus epidermidis",
    "coagulase negative staphylococcus": "staphylococcus epidermidis",
    "coagulase-negative staphylococci": "staphylococcus epidermidis",
    "e. faecalis": "enterococcus faecalis", "e. faecium": "enterococcus faecium",
    "enterococcus": "enterococcus spp.",
    "s. pneumoniae": "streptococcus pneumoniae", "pneumococcus": "streptococcus pneumoniae",
    "s. pyogenes": "streptococcus pyogenes", "gas": "streptococcus pyogenes",
    "s. agalactiae": "streptococcus agalactiae", "gbs": "streptococcus agalactiae",
    "viridans streptococci": "streptococcus viridans",
    "h. influenzae": "haemophilus influenzae",
    "n. meningitidis": "neisseria meningitidis", "meningococcus": "neisseria meningitidis",
    "l. monocytogenes": "listeria monocytogenes", "listeria": "listeria monocytogenes",
    "m. catarrhalis": "moraxella catarrhalis",
    "clostridium difficile": "clostridioides difficile", "c. difficile": "clostridioides difficile",
    "anaerobes": "anaerobes",
}

_ENTEROBACTERALES_GENERA = frozenset({
    "escherichia", "klebsiella", "enterobacter", "citrobacter", "serratia",
    "proteus", "providencia", "morganella", "salmonella", "shigella", "hafnia",
    "raoultella", "pantoea", "yersinia", "cronobacter", "edwardsiella",
})
_MORGANELLACEAE = frozenset({"proteus", "providencia", "morganella"})
# Genera the ESBL prediction applies to (mirrors clinical_data.ESBL_PRODUCERS).
_ESBL_GENERA = frozenset({
    "escherichia", "klebsiella", "proteus", "enterobacter", "citrobacter",
    "serratia", "morganella", "providencia", "hafnia",
})
# Chromosomal inducible AmpC (mirrors clinical_data.AMPC_PRODUCERS).
_AMPC_GENERA = frozenset({"enterobacter", "serratia", "morganella", "providencia", "hafnia"})
_GRAM_POS_GENERA = frozenset({
    "staphylococcus", "streptococcus", "enterococcus", "listeria",
    "corynebacterium", "bacillus", "clostridium", "clostridioides",
    "micrococcus", "propionibacterium", "cutibacterium",
})
_GRAM_NEG_GENERA = _ENTEROBACTERALES_GENERA | frozenset({
    "pseudomonas", "acinetobacter", "stenotrophomonas", "haemophilus",
    "neisseria", "moraxella", "campylobacter", "legionella", "burkholderia",
    "vibrio", "rickettsia", "enterobacterales",
})

_MRSA_TEXT = ("mrsa", "methicillin resistant", "methicillin-resistant",
              "pbp2a", "meca positive")
_VRE_TEXT = ("vre", "vancomycin resistant enterococc", "vancomycin-resistant enterococc")


@dataclass(frozen=True)
class Organism:
    raw: str
    key: str = ""                 # canonical lower-case name; "" when unknown
    genus: str = ""
    species: str = ""             # "" for genus-level / unspeciated names
    groups: FrozenSet[str] = field(default_factory=frozenset)

    @property
    def known(self) -> bool:
        return bool(self.key)

    def is_(self, group: str) -> bool:
        return group in self.groups

    @property
    def gram(self) -> Optional[str]:
        if "gram_positive" in self.groups:
            return "positive"
        if "gram_negative" in self.groups:
            return "negative"
        return None

    @property
    def display(self) -> str:
        return self.raw.strip() or "Unknown organism"


def _clean(name: str) -> str:
    n = (name or "").lower()
    n = re.sub(r"\(.*?\)", " ", n)            # drop parentheticals ("(لاهوائيات)")
    n = re.sub(r"[^a-z0-9.\- ]+", " ", n)     # drop non-latin leftovers
    return re.sub(r"\s+", " ", n).strip()


def _has_word(text: str, word: str) -> bool:
    return re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", text) is not None


@lru_cache(maxsize=512)
def identify(name: str) -> Organism:
    """Resolve a free-text organism name. Never raises; unknown -> no groups."""
    raw = name or ""
    cleaned = _clean(raw)
    if not cleaned:
        return Organism(raw=raw)

    groups = set()
    # Name-level resistance flags are read from the ORIGINAL text, before
    # aliasing folds "MRSA" into "staphylococcus aureus".
    if any(_has_word(cleaned, t) if " " not in t and "-" not in t else t in cleaned
           for t in _MRSA_TEXT):
        groups.add("name_mrsa")
    if any(_has_word(cleaned, t) if " " not in t and "-" not in t else t in cleaned
           for t in _VRE_TEXT):
        groups.add("name_vre")

    key = _ALIASES.get(cleaned, cleaned)
    if "name_vre" in groups and not key.startswith("enterococcus"):
        key = "enterococcus spp."
    if "name_mrsa" in groups and not key.startswith("staphylococcus"):
        key = "staphylococcus aureus"

    parts = key.split()
    genus = parts[0]
    species = ""
    if len(parts) > 1 and parts[1] not in ("spp.", "spp", "sp.", "sp", "species"):
        species = parts[1]

    if genus in _ENTEROBACTERALES_GENERA or genus == "enterobacterales":
        groups.add("enterobacterales")
    if genus in _MORGANELLACEAE:
        groups.add("morganellaceae")
    if genus in _ESBL_GENERA or genus == "enterobacterales":
        groups.add("esbl_capable")
    if (genus in _AMPC_GENERA
            or (genus == "citrobacter" and species != "koseri")
            or genus == "pseudomonas"):
        groups.add("ampc_inducible")
    # IDSA AMR guidance: the organisms at clinically significant risk of AmpC
    # induction on therapy are E. cloacae complex, K. aerogenes, C. freundii.
    if genus == "enterobacter" or (genus == "citrobacter" and species == "freundii"):
        groups.add("ampc_high_risk")
    for g in ("pseudomonas", "acinetobacter", "stenotrophomonas", "klebsiella",
              "staphylococcus", "enterococcus", "streptococcus", "salmonella",
              "shigella"):
        if genus == g:
            groups.add(g)
    if genus == "staphylococcus" and species == "aureus":
        groups.add("s_aureus")
    if genus == "enterococcus" and species == "faecium":
        groups.add("e_faecium")
    if genus in _GRAM_POS_GENERA:
        groups.add("gram_positive")
    elif genus in _GRAM_NEG_GENERA:
        groups.add("gram_negative")

    return Organism(raw=raw, key=key, genus=genus, species=species,
                    groups=frozenset(groups))


# ── intrinsic resistance lookup (table lives in clinical_data) ────────────
def intrinsic_table_keys(name: str) -> Tuple[str, ...]:
    """Which rows of INTRINSIC_RESISTANCE apply to this organism.

    Exact species row first; otherwise the genus-level row; a genus-only name
    whose genus has only species rows gets the INTERSECTION of those rows -
    what is intrinsic for every listed species is intrinsic for the genus, and
    nothing else may be assumed. Unknown / empty names match nothing.
    """
    org = identify(name)
    if not org.known:
        return ()
    table = INTRINSIC_RESISTANCE
    if "name_vre" in org.groups and "vre" in table:
        return ("vre",)
    if org.key in table:
        return (org.key,)
    for cand in (f"{org.genus} spp.", org.genus):
        if cand in table:
            return (cand,)
    return ()


@lru_cache(maxsize=512)
def intrinsic_drugs(name: str) -> FrozenSet[str]:
    org = identify(name)
    keys = intrinsic_table_keys(name)
    if keys:
        out: set = set()
        for k in keys:
            out.update(INTRINSIC_RESISTANCE[k])
        return frozenset(out)
    if org.known and not org.species:
        rows = [set(v) for k, v in INTRINSIC_RESISTANCE.items()
                if k.split()[0] == org.genus]
        if rows:
            return frozenset(set.intersection(*rows))
    return frozenset()


def is_intrinsic(name: str, drug: str) -> bool:
    return drug in intrinsic_drugs(name)


def strip_intrinsic(name: str, sir_map: dict) -> dict:
    """Copy of `sir_map` without the drugs this organism is intrinsically
    resistant to. Intrinsic results carry no information about ACQUIRED
    resistance, so mechanism inference and MDR counting must not see them."""
    drop = intrinsic_drugs(name)
    if not drop:
        return dict(sir_map)
    return {d: v for d, v in sir_map.items() if d not in drop}


def matches_any(name: str, names: Iterable[str]) -> bool:
    """Is `name` one of `names`? Compared on canonical identity, so
    "Escherichia coli" matches a rule written for "E. coli"; a genus-level
    entry ("Klebsiella spp.") matches every species of that genus. An unknown
    or empty organism matches nothing."""
    org = identify(name)
    if not org.known:
        return False
    for n in names:
        other = identify(n)
        if not other.known:
            continue
        if other.key == org.key:
            return True
        if other.genus == org.genus and not (other.species and org.species):
            return True
    return False


# ── coarse equivalence used by the pathogenicity lists ────────────────────
# (kept as-is: these lists compare organisms at "is this the same bug for
# contamination purposes" granularity, e.g. every Klebsiella is one entry.)
_ORG_CANON_MAP = {
    "e. coli": "escherichia coli", "e.coli": "escherichia coli",
    "escherichia coli": "escherichia coli",
    "enterohemorrhagic e. coli": "escherichia coli o157",
    "escherichia coli o157:h7": "escherichia coli o157",
    "klebsiella spp.": "klebsiella", "klebsiella pneumoniae": "klebsiella",
    "klebsiella oxytoca": "klebsiella", "klebsiella": "klebsiella",
    "proteus mirabilis": "proteus", "proteus spp.": "proteus", "proteus": "proteus",
    "enterococcus faecalis": "enterococcus", "enterococcus spp.": "enterococcus",
    "enterococcus faecium": "enterococcus", "enterococcus": "enterococcus",
    "vre": "vre",
    "h. influenzae": "haemophilus influenzae",
    "haemophilus influenzae": "haemophilus influenzae",
    "staphylococcus aureus": "staphylococcus aureus", "mssa": "staphylococcus aureus",
    "mrsa": "mrsa",
    "staphylococcus epidermidis": "cons",
    "staphylococcus saprophyticus": "staphylococcus saprophyticus",
    "coagulase negative staphylococcus": "cons",
    "coagulase-negative staphylococci": "cons", "cons": "cons",
    "streptococcus viridans": "viridans streptococci",
    "viridans streptococci": "viridans streptococci",
    "corynebacterium spp.": "corynebacterium", "corynebacterium": "corynebacterium",
    "campylobacter jejuni": "campylobacter", "campylobacter spp.": "campylobacter",
    "campylobacter": "campylobacter",
    "salmonella spp.": "salmonella", "salmonella": "salmonella",
    "shigella spp.": "shigella", "shigella": "shigella",
    "streptococcus pneumoniae": "streptococcus pneumoniae",
    "s. pneumoniae": "streptococcus pneumoniae",
    "pseudomonas aeruginosa": "pseudomonas aeruginosa",
    "acinetobacter baumannii": "acinetobacter baumannii",
    "stenotrophomonas maltophilia": "stenotrophomonas maltophilia",
    "legionella pneumophila": "legionella", "legionella": "legionella",
    "mycoplasma spp.": "mycoplasma", "mycoplasma pneumoniae": "mycoplasma",
    "moraxella catarrhalis": "moraxella catarrhalis",
    "neisseria meningitidis": "neisseria meningitidis",
    "neisseria spp.": "neisseria",
    "listeria monocytogenes": "listeria monocytogenes",
    "streptococcus agalactiae": "streptococcus agalactiae",
    "gbs": "streptococcus agalactiae",
    "anaerobes (لاهوائيات)": "anaerobes", "anaerobes": "anaerobes",
    "clostridioides difficile": "c. difficile", "clostridium difficile": "c. difficile",
    "candida albicans": "candida", "candida spp.": "candida", "candida": "candida",
}


def canon_org(name: str) -> str:
    n = re.sub(r"\s+", " ", (name or "").strip().lower())
    return _ORG_CANON_MAP.get(n, n)


def org_in(name: str, group: Iterable[str]) -> bool:
    """Spelling-independent membership test for organism names."""
    target = canon_org(name)
    if not target:
        return False
    return any(canon_org(g) == target for g in group)
