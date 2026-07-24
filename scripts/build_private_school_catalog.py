"""Build the compact private-school catalog bundled with the API.

Source:
    INEP - Microdados do Censo Escolar da Educacao Basica 2025

The generated JSONL.GZ contains only private schools reported as active in the
latest census snapshot. It intentionally keeps only public institutional data
needed by the prospecting workflow.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
from pathlib import Path


FIELDS = (
    "NU_ANO_CENSO",
    "SG_UF",
    "NO_MUNICIPIO",
    "NO_ENTIDADE",
    "CO_ENTIDADE",
    "TP_DEPENDENCIA",
    "TP_CATEGORIA_ESCOLA_PRIVADA",
    "TP_SITUACAO_FUNCIONAMENTO",
    "DS_ENDERECO",
    "NU_ENDERECO",
    "DS_COMPLEMENTO",
    "NO_BAIRRO",
    "CO_CEP",
    "NU_DDD",
    "NU_TELEFONE",
    "LATITUDE",
    "LONGITUDE",
    "NU_CNPJ_ESCOLA_PRIVADA",
    "NU_CNPJ_MANTENEDORA",
    "IN_INTERNET",
    "IN_INTERNET_ADMINISTRATIVO",
    "IN_BANDA_LARGA",
    "IN_REDES_SOCIAIS",
    "QT_PROF_ADMINISTRATIVOS",
    "QT_PROF_GESTAO",
    "IN_COMUM_CRECHE",
    "IN_COMUM_PRE",
    "IN_COMUM_FUND_AI",
    "IN_COMUM_FUND_AF",
    "IN_COMUM_MEDIO_MEDIO",
)


def digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def normalize_phone(ddd: str | None, number: str | None) -> str | None:
    raw = digits(number)
    area = digits(ddd)
    if not raw:
        return None
    if raw.startswith("55") and len(raw) in {12, 13}:
        return f"+{raw}"
    if len(raw) in {10, 11}:
        return f"+55{raw}"
    if area and len(area) == 2 and len(raw) in {8, 9}:
        return f"+55{area}{raw}"
    return None


def truthy(value: str | None) -> bool:
    return str(value or "").strip() == "1"


def integer(value: str | None) -> int:
    try:
        return int(float(str(value or "0").replace(",", ".")))
    except ValueError:
        return 0


def stages(row: dict[str, str]) -> list[str]:
    mapping = {
        "IN_COMUM_CRECHE": "creche",
        "IN_COMUM_PRE": "pre-escola",
        "IN_COMUM_FUND_AI": "fundamental anos iniciais",
        "IN_COMUM_FUND_AF": "fundamental anos finais",
        "IN_COMUM_MEDIO_MEDIO": "ensino medio",
    }
    return [label for field, label in mapping.items() if truthy(row.get(field))]


def build(source: Path, destination: Path) -> dict[str, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    counts = {"source_rows": 0, "active_private": 0, "with_phone": 0, "with_cnpj": 0}
    # INEP publishes this table in Windows-1252.
    with source.open("r", encoding="cp1252", newline="") as source_file:
        reader = csv.DictReader(source_file, delimiter=";")
        missing = sorted(set(FIELDS) - set(reader.fieldnames or []))
        if missing:
            raise RuntimeError(f"Missing INEP columns: {', '.join(missing)}")
        with gzip.open(destination, "wt", encoding="utf-8", newline="\n") as output:
            for row in reader:
                counts["source_rows"] += 1
                if row["TP_DEPENDENCIA"] != "4" or row["TP_SITUACAO_FUNCIONAMENTO"] != "1":
                    continue
                school_code = digits(row["CO_ENTIDADE"])
                if not school_code:
                    continue
                phone = normalize_phone(row.get("NU_DDD"), row.get("NU_TELEFONE"))
                cnpj = digits(row.get("NU_CNPJ_ESCOLA_PRIVADA")) or digits(row.get("NU_CNPJ_MANTENEDORA"))
                item = {
                    "census_year": integer(row["NU_ANO_CENSO"]),
                    "school_code": school_code,
                    "school_name": row["NO_ENTIDADE"].strip(),
                    "state": row["SG_UF"].strip(),
                    "city": row["NO_MUNICIPIO"].strip(),
                    "address": " ".join(
                        part.strip()
                        for part in (
                            row.get("DS_ENDERECO", ""),
                            row.get("NU_ENDERECO", ""),
                            row.get("DS_COMPLEMENTO", ""),
                            row.get("NO_BAIRRO", ""),
                        )
                        if part and part.strip()
                    ),
                    "postal_code": digits(row.get("CO_CEP")) or None,
                    "phone": phone,
                    "cnpj": cnpj or None,
                    "latitude": row.get("LATITUDE") or None,
                    "longitude": row.get("LONGITUDE") or None,
                    "private_category": row.get("TP_CATEGORIA_ESCOLA_PRIVADA") or None,
                    "has_internet": truthy(row.get("IN_INTERNET")),
                    "has_admin_internet": truthy(row.get("IN_INTERNET_ADMINISTRATIVO")),
                    "has_broadband": truthy(row.get("IN_BANDA_LARGA")),
                    "has_social_media": truthy(row.get("IN_REDES_SOCIAIS")),
                    "administrative_staff": integer(row.get("QT_PROF_ADMINISTRATIVOS")),
                    "management_staff": integer(row.get("QT_PROF_GESTAO")),
                    "stages": stages(row),
                }
                output.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
                counts["active_private"] += 1
                counts["with_phone"] += int(bool(phone))
                counts["with_cnpj"] += int(bool(cnpj))
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.destination), ensure_ascii=False))


if __name__ == "__main__":
    main()
