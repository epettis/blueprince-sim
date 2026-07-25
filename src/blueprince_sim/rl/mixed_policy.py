"""Explicit exploit/explore mixing for MaskablePPO rollouts.

Each *decision* is taken in one of two behavior modes, re-rolled per decision
by default (or coherently per episode). Per-decision keeps a long episode
mostly on-policy: at ``exploit_prob=0.9`` only ~1 action in 10 explores,
whereas a per-episode explore roll would make a whole 50-70 decision episode a
random walk that never reaches the Antechamber.

- EXPLOIT (probability ``exploit_prob``): sample the masked policy
  distribution at low temperature (``exploit_temp`` < 1 sharpens toward the
  argmax) - "play the best known policy."
- EXPLORE (probability ``1 - exploit_prob``): sample at high temperature
  (``explore_temp`` > 1 flattens the distribution, giving
  low-probability / low-confidence actions that still carry estimated value
  a real chance), blended with an ``explore_eps`` uniform floor over LEGAL
  actions so even near-zero-probability actions occasionally get tried.

Illegal (masked) actions have zero probability in both modes.

PPO correctness caveat: the log-probs stored in the rollout buffer are those
of the adjusted behavior distribution, so PPO's importance ratio treats the
behavior policy as pi_old. That is mildly off-policy for the underlying
network distribution; PPO's clipping bounds the bias, and with
``exploit_prob=1.0, exploit_temp=1.0`` the mechanism reduces exactly to
vanilla MaskablePPO. Evaluation (``model.predict``) is untouched and stays
deterministic argmax.
"""

from __future__ import annotations

import numpy as np
import torch
from sb3_contrib.common.maskable.policies import MaskableMultiInputActorCriticPolicy


class MixedExplorationPolicy(MaskableMultiInputActorCriticPolicy):
    def __init__(self, *args, exploit_temp: float = 0.5, explore_temp: float = 1.5,
                 explore_eps: float = 0.05, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.exploit_temp = float(exploit_temp)
        self.explore_temp = float(explore_temp)
        self.explore_eps = float(explore_eps)
        # Runtime mode state; configured by set_mode_config (not serialized).
        self.exploit_prob = 1.0
        self.per_decision = False
        self._mode_rng = np.random.default_rng(0)
        self.env_modes: np.ndarray = np.ones(1, dtype=bool)  # True = exploit
        self.last_modes: np.ndarray = np.ones(1, dtype=bool)  # modes of the last forward()

    # ------------------------------------------------------------ mode state

    def set_mode_config(self, exploit_prob: float, per_decision: bool,
                        n_envs: int, seed: int) -> None:
        """Configure rollout-time mode mixing; call after construction or load.

        Mode state is deliberately not serialized into checkpoints, so the
        current run's flags always win over whatever a resumed checkpoint
        stored. Also rolls the initial per-env modes.
        """
        self.exploit_prob = float(exploit_prob)
        self.per_decision = per_decision
        self._mode_rng = np.random.default_rng(seed)
        self.env_modes = self._mode_rng.random(n_envs) < self.exploit_prob

    def resample_modes(self, done_indices) -> None:
        """Re-roll the sticky per-episode mode for envs whose episode just ended.

        Called by the training callback in per-episode granularity only.
        """
        for i in done_indices:
            self.env_modes[i] = self._mode_rng.random() < self.exploit_prob

    # --------------------------------------------------------------- forward

    def forward(self, obs, deterministic: bool = False, action_masks=None):
        """Mirror of the parent forward, with mode-dependent sampling.

        Follows MaskableActorCriticPolicy.forward (sb3-contrib 2.9): feature
        extraction -> latents -> value + masked distribution; only the
        sampling step differs.
        """
        features = self.extract_features(obs)
        if self.share_features_extractor:
            latent_pi, latent_vf = self.mlp_extractor(features)
        else:
            pi_features, vf_features = features
            latent_pi = self.mlp_extractor.forward_actor(pi_features)
            latent_vf = self.mlp_extractor.forward_critic(vf_features)
        values = self.value_net(latent_vf)
        distribution = self._get_action_dist_from_latent(latent_pi)
        if action_masks is not None:
            distribution.apply_masking(action_masks)

        if deterministic:
            self.last_modes = np.ones(len(next(iter(obs.values()))), dtype=bool)
            actions = distribution.get_actions(deterministic=True)
            return actions, values, distribution.log_prob(actions)

        logits = distribution.distribution.logits  # masked entries ~ -inf
        batch = logits.shape[0]
        modes = self._modes_for_batch(batch)
        self.last_modes = np.asarray(modes, dtype=bool)
        exploit_t = torch.as_tensor(modes, device=logits.device)

        temps = torch.where(
            exploit_t,
            torch.tensor(self.exploit_temp, device=logits.device),
            torch.tensor(self.explore_temp, device=logits.device),
        ).unsqueeze(1)
        probs = torch.softmax(logits / temps, dim=1)

        eps = torch.where(
            exploit_t,
            torch.tensor(0.0, device=logits.device),
            torch.tensor(self.explore_eps, device=logits.device),
        ).unsqueeze(1)
        if float(eps.max()) > 0.0:
            if action_masks is not None:
                legal = torch.as_tensor(action_masks, device=logits.device) \
                    .reshape(logits.shape).float()
            else:
                # sb3-contrib masks logits to -1e8; anything above -1e7 is legal
                legal = (logits > -1e7).float()
            uniform = legal / legal.sum(dim=1, keepdim=True).clamp(min=1.0)
            probs = (1.0 - eps) * probs + eps * uniform

        behavior = torch.distributions.Categorical(probs=probs)
        actions = behavior.sample()
        return actions, values, behavior.log_prob(actions)

    def _modes_for_batch(self, batch: int) -> np.ndarray:
        """Exploit-mode flags (True = exploit) for this forward batch.

        Per-decision granularity rolls fresh flags every call; per-episode
        reuses the sticky ``env_modes``.
        """
        if self.per_decision:
            return self._mode_rng.random(batch) < self.exploit_prob
        if len(self.env_modes) != batch:
            # Batch size changed (e.g. policy reused with a different vec env):
            # re-roll to fit rather than crash.
            self.env_modes = self._mode_rng.random(batch) < self.exploit_prob
        return self.env_modes
