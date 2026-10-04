"""
Verificação de assinatura dos arquivos .jws de divulgação do TSE (Eleições 2026).
Formato: cabecalho.dados.assinatura (Base64URL), algoritmo EdDSA/Ed25519.
As chaves públicas ficam fixas aqui, conforme o 'Manual de verificação dos arquivos JWS'
(docs/tse_oficial/manual-verificacao-jws.pdf) — nunca são lidas do próprio arquivo.
"""
import base64
import json
from typing import Any, Dict

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# Apêndices A e B do manual do TSE
CHAVES_TSE: Dict[str, Dict[str, str]] = {
    "oficial": {
        "kid": "sNbt9Q_fLS65zE1_ZLNV-XRRwPY",
        "x": "kWlpNHjuws1csyQZwzn3Fhzbi3RD435RbpThtSr4hMc",
    },
    "desenvolvimento": {
        "kid": "pEGrlis0i8vO2Bz7Ergwr0MnKfg",
        "x": "81fm_gXW6Q5gBWrGJkE7j5MOS5vmTnRqqFHfdMeRbsw",
    },
}


class JWSInvalidoError(Exception):
    """Arquivo .jws malformado ou com assinatura inválida."""


def _b64url_decode(parte: str) -> bytes:
    return base64.urlsafe_b64decode(parte + "=" * (-len(parte) % 4))


class JWSVerifier:
    """Verifica arquivos .jws do TSE com uma chave Ed25519 fixa."""

    def __init__(self, kid: str, x_b64url: str):
        self.kid = kid
        self._chave = Ed25519PublicKey.from_public_bytes(_b64url_decode(x_b64url))

    @classmethod
    def do_ambiente(cls, ambiente: str) -> "JWSVerifier":
        if ambiente not in CHAVES_TSE:
            raise ValueError(f"Ambiente JWS desconhecido: '{ambiente}'. Opções: {list(CHAVES_TSE)}")
        chave = CHAVES_TSE[ambiente]
        return cls(chave["kid"], chave["x"])

    def verificar(self, conteudo: str) -> Dict[str, Any]:
        """Valida a assinatura e retorna o JSON de resultado decodificado."""
        partes = conteudo.strip().split(".")
        if len(partes) != 3:
            raise JWSInvalidoError("JWS deve conter 3 partes separadas por ponto")
        cab_b64, dados_b64, assin_b64 = partes

        try:
            cabecalho = json.loads(_b64url_decode(cab_b64))
        except (ValueError, json.JSONDecodeError) as e:
            raise JWSInvalidoError(f"Cabeçalho JWS ilegível: {e}") from e

        if cabecalho.get("alg") != "EdDSA":
            raise JWSInvalidoError(f"Algoritmo inesperado: {cabecalho.get('alg')!r}")
        if cabecalho.get("kid") != self.kid:
            raise JWSInvalidoError(f"Chave (kid) inesperada: {cabecalho.get('kid')!r}")

        try:
            self._chave.verify(_b64url_decode(assin_b64), f"{cab_b64}.{dados_b64}".encode("ascii"))
        except (InvalidSignature, ValueError) as e:
            raise JWSInvalidoError("Assinatura JWS inválida") from e

        try:
            return json.loads(_b64url_decode(dados_b64))
        except (ValueError, json.JSONDecodeError) as e:
            raise JWSInvalidoError(f"Payload JWS não é JSON válido: {e}") from e
