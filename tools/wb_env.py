"""Environment bootstrap for Ally. Import this before anything that talks to W&B.

Three jobs, in order:
  1. Load .env into os.environ (shell values always win).
  2. Point OpenSSL at certifi's CA bundle. On Windows, stdlib ssl reads the
     Windows trust store, which holds a stale Let's Encrypt root and rejects
     api.inference.wandb.ai with "certificate has expired". requests and httpx
     vendor certifi so they are unaffected; anything on stdlib urllib is not.
  3. Assert the config we need is actually present, and fail loudly if not.

Step 3 is Dos-and-donts 1.6: a startup check that names what is missing beats
a confusing failure thirty minutes into a run.
"""

from __future__ import annotations

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
REQUIRED = ("WANDB_API_KEY", "WANDB_ENTITY", "WANDB_PROJECT")

# api.inference.wandb.ai sits behind Cloudflare, which returns 403 error 1010
# to the default "Python-urllib/3.x" user-agent. Any real UA string is accepted.
USER_AGENT = "ally/0.1"


class ConfigError(RuntimeError):
    """Raised when the environment cannot support a run."""


def load_dotenv(path: pathlib.Path | None = None) -> pathlib.Path | None:
    """Load KEY=VALUE lines from .env. Existing os.environ values take priority."""
    target = path or ROOT / ".env"
    if not target.exists():
        return None
    for raw in target.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return target


def use_certifi_bundle() -> str | None:
    """Point OpenSSL and friends at certifi's bundle instead of the OS store."""
    try:
        import certifi
    except ImportError:
        return None
    bundle = certifi.where()
    # SSL_CERT_FILE reaches stdlib ssl via set_default_verify_paths(); the other
    # two cover libraries that read their own variable, and any subprocess.
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        os.environ.setdefault(var, bundle)
    return bundle


def bootstrap(require: bool = True) -> dict[str, str]:
    """Load config, repair TLS, verify required keys. Returns the W&B settings."""
    load_dotenv()
    use_certifi_bundle()

    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing and require:
        raise ConfigError(
            "Missing required environment: "
            + ", ".join(missing)
            + f"\nSet them in {ROOT / '.env'}. WANDB_ENTITY is the bare team slug "
            "(e.g. my-team), never a wandb.ai URL."
        )

    entity = os.environ.get("WANDB_ENTITY", "")
    if "://" in entity or "/" in entity:
        raise ConfigError(
            f"WANDB_ENTITY looks like a URL or path: {entity!r}\n"
            "Use the bare team slug only. A malformed entity makes W&B Inference "
            "return 'Invalid Authentication', which reads like a bad API key."
        )

    return {
        "api_key": os.environ.get("WANDB_API_KEY", ""),
        "entity": entity,
        "project": os.environ.get("WANDB_PROJECT", ""),
        # Weave wants "entity/project"; Inference wants the same string as project.
        "ref": f"{entity}/{os.environ.get('WANDB_PROJECT', '')}",
    }


def openai_client():
    """An OpenAI client wired to W&B Inference, with usage attributed to the team."""
    from openai import OpenAI

    cfg = bootstrap()
    # openai 3.x no longer accepts project= as 1.x did; the header is the
    # documented fallback and attributes usage to the team either way.
    return OpenAI(
        base_url="https://api.inference.wandb.ai/v1",
        api_key=cfg["api_key"],
        default_headers={"OpenAI-Project": cfg["ref"]},
    )
