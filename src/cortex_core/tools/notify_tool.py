"""Cliente de notificacoes externas via Apprise Hub (rede interna notify_bus)."""

import logging
from typing import List, Optional

import httpx

logger = logging.getLogger("cortex.tools.notify")


class AppriseNotifier:
    """Despacha alertas e respostas externas quando o morador esta fora de casa."""

    def __init__(self, apprise_url: str, default_tag: str = "admin") -> None:
        self._url = apprise_url.strip()
        self._default_tag = default_tag.strip() or "admin"

    async def send(
        self,
        title: str,
        body: str,
        tags: Optional[List[str]] = None,
        msg_format: str = "text",
    ) -> bool:
        payload = {
            "title": title,
            "body": body,
            "tag": ",".join(tags) if tags else self._default_tag,
            "format": msg_format,
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(self._url, json=payload)
                if resp.status_code in (200, 201, 204):
                    return True
                logger.warning("Apprise retornou status %s", resp.status_code)
                return False
        except httpx.HTTPError as exc:
            logger.warning("Falha ao enviar notificacao via Apprise: %s", exc)
            return False
