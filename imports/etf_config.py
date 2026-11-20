"""Lecture du référentiel des actifs (etfs.toml à la racine du projet)."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "etfs.toml"
FREQUENCES = ("daily", "weekly")


@dataclass(frozen=True)
class Actif:
    id: str
    ticker: str
    table: str
    nom: str
    frequence: str
    devise: str = "EUR"
    categories: tuple[str, ...] = field(default_factory=tuple)
    affiche: bool = True


@dataclass(frozen=True)
class Config:
    bq_project: str
    bq_dataset: str
    date_debut_defaut: str
    parite: Actif
    actifs: tuple[Actif, ...]
    categories: dict[str, str] = field(default_factory=dict)

    def table_id(self, actif: Actif) -> str:
        return f"{self.bq_project}.{self.bq_dataset}.{actif.table}"

    def a_importer(self, frequence: str = "all", ids: list[str] | None = None) -> list[Actif]:
        """Parité + actifs filtrés par fréquence ("daily", "weekly", "all") ou par id."""
        tous = [self.parite, *self.actifs]
        if ids:
            voulus = {i.upper() for i in ids}
            inconnus = voulus - {a.id for a in tous}
            if inconnus:
                raise ValueError(f"Identifiants inconnus dans etfs.toml : {sorted(inconnus)}")
            return [a for a in tous if a.id in voulus]
        if frequence == "all":
            return tous
        return [a for a in tous if a.frequence == frequence]


def _actif(data: dict) -> Actif:
    actif = Actif(**{**data, "categories": tuple(data.get("categories", ()))})
    if actif.frequence not in FREQUENCES:
        raise ValueError(f"{actif.id} : fréquence '{actif.frequence}' invalide, attendu {FREQUENCES}")
    if actif.devise not in ("EUR", "USD"):
        raise ValueError(f"{actif.id} : devise '{actif.devise}' non gérée")
    return actif


def charger_config(path: Path = CONFIG_PATH) -> Config:
    with open(path, "rb") as f:
        data = tomllib.load(f)

    actifs = tuple(_actif(a) for a in data["actifs"])
    parite = _actif(data["parite"])

    ids = [a.id for a in actifs] + [parite.id]
    tables = [a.table for a in actifs] + [parite.table]
    for nom, valeurs in (("id", ids), ("table", tables)):
        doublons = {v for v in valeurs if valeurs.count(v) > 1}
        if doublons:
            raise ValueError(f"{nom} en double dans {path.name} : {sorted(doublons)}")

    projet = data["projet"]
    quota = projet["quota_appels_jour"]
    for frequence in FREQUENCES:
        n = sum(a.frequence == frequence for a in (parite, *actifs))
        if n > quota:
            raise ValueError(
                f"{n} actifs en '{frequence}' pour un quota EODHD de {quota} appels/jour : "
                "passer des actifs dans l'autre fréquence"
            )

    categories = data.get("categories", {})
    inconnues = {c for a in (parite, *actifs) for c in a.categories} - categories.keys()
    if inconnues:
        raise ValueError(f"Catégories sans libellé dans [categories] : {sorted(inconnues)}")

    return Config(
        categories=categories,
        bq_project=projet["bq_project"],
        bq_dataset=projet["bq_dataset"],
        date_debut_defaut=projet["date_debut_defaut"],
        parite=parite,
        actifs=actifs,
    )
