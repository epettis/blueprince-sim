"""Vault: registers the deposit-box capability special_items.py's vault-box
gate keys off.

``special_items.can_open_vault_box`` reads ``Capability.VAULT`` (via
``provides_capability``) to gate the deposit-box mechanic to this room -- see
that function's own docstring for the box logic.
"""

from __future__ import annotations

from .. import Capability, provides

provides("vault", Capability.VAULT)
