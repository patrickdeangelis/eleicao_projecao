"""
Value Objects para o domínio eleitoral do SPETR.
Imutáveis e independentes de frameworks externos.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class Cargo(str, Enum):
    PRESIDENTE = "1"
    GOVERNADOR = "3"
    SENADOR = "5"
    PREFEITO = "11"


class StatusCall(str, Enum):
    INDEFINIDO = "INDEFINIDO"
    VITORIA_PROJETADA = "VITORIA_PROJETADA"
    MATEMATICAMENTE_ELEITO = "MATEMATICAMENTE_ELEITO"


class TipoEstrato(str, Enum):
    CAPITAL = "CAPITAL"
    GRANDE_CIDADE = "GRANDE_CIDADE"
    INTERIOR_REMANESCENTE = "INTERIOR_REMANESCENTE"
    ESTADO_TOTAL = "ESTADO_TOTAL"


UF_VALIDAS: Tuple[str, ...] = (
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA",
    "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN",
    "RO", "RR", "RS", "SC", "SE", "SP", "TO", "ZZ"
)


@dataclass(frozen=True)
class UF:
    sigla: str

    def __post_init__(self):
        s = self.sigla.strip().upper()
        if s not in UF_VALIDAS:
            raise ValueError(f"UF inválida: '{self.sigla}'. Válidas: {UF_VALIDAS}")
        object.__setattr__(self, "sigla", s)

    def __str__(self) -> str:
        return self.sigla


@dataclass(frozen=True)
class CodigoMunicipioTSE:
    codigo: str

    def __post_init__(self):
        c = self.codigo.strip().zfill(5)
        if not c.isdigit() or len(c) != 5:
            raise ValueError(f"Código TSE de município deve conter 5 dígitos: '{self.codigo}'")
        object.__setattr__(self, "codigo", c)

    def __str__(self) -> str:
        return self.codigo
