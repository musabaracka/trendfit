import copy
from collections import defaultdict

import numpy as np

from ..base import BaseEstimator
from ..options import OPTIONS


class BootstrapEstimator(BaseEstimator):

    def __init__(self, model, n_samples=1000, random_state=None,
                 save_models=False):

        self.model = model
        self.n_samples = n_samples
        self.save_models = save_models

        if isinstance(random_state, np.random.RandomState):
            self.random_state = random_state
        else:
            self.random_state = np.random.RandomState(seed=random_state)

        super().__init__()

        self._parameter_dists = defaultdict(list)
        self._models = []

    @property
    def parameters(self):
        return self.model.parameters

    @property
    def parameter_dists(self):
        return self._parameter_dists

    @property
    def residuals(self):
        return self.model.residuals

    @property
    def models(self):
        return self._models

    def generate_bootstrap_sample(self, random_state=None):
        if not self.model._fitted:
            raise ValueError("Model not fitted.")

        if random_state is None:
            random_state = self.random_state

        return self._generate_bootstrap_sample(random_state)

    def _generate_bootstrap_sample(self):
        raise NotImplementedError()

    def _fit(self, t, y):
        self.model.fit(t, y)

        def fit_sample(random_state=None):
            mb = copy.deepcopy(self.model)
            yb = self.generate_bootstrap_sample(random_state)

            mb.fit(t, yb)

            pb = mb.parameters.copy()

            if self.save_models:
                return mb, pb
            else:
                return None, pb

        if OPTIONS['use_dask']:
            import dask
            dlyd = [dask.delayed(fit_sample)(np.random.RandomState())
                    for _ in range(self.n_samples)]
            res = dask.compute(*dlyd)
        else:
            res = [fit_sample() for _ in range(self.n_samples)]

        for mb, pb in res:
            if self.save_models:
                self._models.append(mb)

            for k, v in pb.items():
                self._parameter_dists[k].append(v)

    def _predict(self, t):
        return self.model.predict(t)

    def get_ci_bounds(self, confidence_level=0.95):
        if not self._fitted:
            raise ValueError("run `.fit()` first")

        ci_bounds = {}
        alpha = 1 - confidence_level

        for k, v in self.parameter_dists.items():
            lower = np.quantile(v, alpha / 2, axis=0)
            upper = np.quantile(v, 1 - alpha / 2, axis=0)

            ci_bounds[k] = [lower, upper]

        return ci_bounds


class ResidualResampling(BootstrapEstimator):
    """Residual Resampling Bootstrap.

    Generate bootstrap samples by (1) randomly resampling the
    residuals of the fitted model and (2) adding it to the predicted
    values.

    """
    def __init__(self, model, **kwargs):
        super().__init__(model, **kwargs)

    def _generate_bootstrap_sample(self, random_state):
        errors = self.model.residuals.copy()
        random_state.shuffle(errors)

        return self.model._y_predict + errors


def _cholesky_decomposition(t, gamma):
    mat = np.triu(gamma**(t[None, :] - t[:, None]))
    np.fill_diagonal(mat, 0.5)

    return np.linalg.cholesky(mat + mat.transpose())


class BlockARWild(BootstrapEstimator):
    """Block Autoregressive Wild Bootstrap.

    Generate bootstrap samples with autocorrelated errors using the
    method described in [add paper].

    This method may be used with non-evenly spaced samples.

    Unlike the Autoregressive Wild Bootstrap method described in that
    paper, the residuals are here split into contiguous blocks
    (equally sized, except maybe for the last block), and
    autocorrelated errors are generated independently for each of these
    blocks.

    One limitation of this approach is that the auto-correlation is
    "reset" each time when jumping from one block to another. However,
    in some cases this might be an acceptable approximation while
    offering great optimization in both speed-up and memory usage.
    Splitting the time-series in only a few number of blocks may
    result in 10x speed-up.

    To use the "full" Autoregressive Wild Bootstrap method, just set a
    block size equal or larger than the actual size of the time
    series.

    """
    def __init__(self, model, block_size=500, ar_coef=None, **kwargs):

        self.block_size = block_size
        self.ar_coef = ar_coef

        super().__init__(model, **kwargs)

    def _generate_bootstrap_err(self, t, residuals, random_state):
        # autoregressive coefficient
        if self.ar_coef is None:
            th = 0.01**(1 / (1.75 * t.size**(1/3)))
            l = 1 / 365.25
            gamma = th**(1. / l)
        else:
            gamma = self.ar_coef

        iid = random_state.normal(loc=0., scale=1., size=t.size)

        n_blocks = max(t.size // self.block_size, 1)
        t_blocks = np.array_split(t, n_blocks)
        residuals_blocks = np.array_split(residuals, n_blocks)
        iid_blocks = np.array_split(iid, n_blocks)

        def _gen_errors_block(tb, rb, iidb):
            L = _cholesky_decomposition(tb, gamma)
            return (L @ iidb).ravel() * rb

        return np.concatenate([
            _gen_errors_block(tb, rb, iidb)
            for tb, rb, iidb in zip(t_blocks, residuals_blocks, iid_blocks)
        ])

    def _generate_bootstrap_sample(self, random_state):
        errors = self._generate_bootstrap_err(self.model._t,
                                              self.model.residuals,
                                              random_state)

        return self.model._y_predict + errors
