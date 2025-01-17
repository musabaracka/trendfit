import numpy as np
from scipy.optimize import dual_annealing

from ..base import BaseEstimator


class LinearNoTrendFourier(BaseEstimator):
    """Linear regression with Fourier terms.

    The Fourier terms allow capturing the periodic variability in the
    time-series.

    No trend is assumed in the time series.

    Notes
    -----
    The model is defined as follows:

    .. math::

       y_t = \alpha + F_t + \epsilon_t

    where :math:`\alpha` is the intercept, :math:`\epsilon_t` is the error
    term and :math:`F_t` is the nth-order approximated Fourier series, i.e.,

    .. math::

       F_t = \sum{j=1}{M} a_j \cos(2 j \pi t) + b_j \sin(2 j \pi t)

    This model is fitted to :math:`\{t, y_t\}` data using ordinary
    least squares (OLS).

    """
    def __init__(self, f_order=3):
        """

        Parameters
        ----------
        f_order : int, optional
            Finite order of the truncated Fourier series (default=3). Set
            it to zero there's no periodic variability in the time series.

        """
        self.f_order = f_order

        self._parameters = {
            'fourier_terms': [],
            'intercept': None,
        }

        super().__init__()

    def _fourier_terms(self, t, degree):
        return [np.cos(2 * degree * np.pi * t),
                np.sin(2 * degree * np.pi * t)]

    def _regressor_terms(self, t):
        reg_terms = []
        reg_idx = {}

        # fourier terms
        if self.f_order:
            for degree in range(1, self.f_order + 1):
                reg_terms += self._fourier_terms(t, degree)

            reg_idx['fourier_terms'] = slice(0, self.f_order * 2)

        # intercept
        reg_terms.append(np.ones(t.size))

        if self.f_order:
            reg_idx['intercept'] = self.f_order * 2
        else:
            reg_idx['intercept'] = 0

        return reg_idx, reg_terms

    def _solve_lstsq(self, t, y, reg_idx, reg_terms):
        mat = np.stack(reg_terms).transpose()

        p, ssr, _, _ = np.linalg.lstsq(mat, y, rcond=None)

        for k, idx in reg_idx.items():
            self._parameters[k] = p[idx]

        return ssr

    def _fit(self, t, y):
        reg_idx, reg_terms = self._regressor_terms(t)

        return self._solve_lstsq(t, y, reg_idx, reg_terms)[0]

    def _compute_y(self, t, reg_idx, reg_terms):
        p = np.empty((len(reg_terms)))

        for k, idx in reg_idx.items():
            p[idx] = self._parameters[k]

        mat = np.stack(reg_terms).transpose()

        return (mat @ p[:, None]).ravel()

    def _predict(self, t):
        reg_idx, reg_terms = self._regressor_terms(t)

        return self._compute_y(t, reg_idx, reg_terms)


class LinearTrendFourier(LinearNoTrendFourier):
    """Linear regression with a single trend and Fourier terms.

    The Fourier terms allow capturing the periodic variability in the
    time-series.

    Notes
    -----
    The model is defined as follows:

    .. math::

       y_t = \alpha + \beta t + F_t + \epsilon_t

    where :math:`\alpha` is the intercept, :math:`\beta` is the slope,
    :math:`\epsilon_t` is the error term and :math:`F_t` is the nth-order
    approximated Fourier series, i.e.,

    .. math::

       F_t = \sum{j=1}{M} a_j \cos(2 j \pi t) + b_j \sin(2 j \pi t)

    This model is fitted to :math:`\{t, y_t\}` data using ordinary
    least squares (OLS).

    """
    def __init__(self, f_order=3):
        """

        Parameters
        ----------
        f_order : int, optional
            Finite order of the truncated Fourier series (default=3). Set
            it to zero there's no periodic variability in the time series.

        """
        super().__init__(f_order)

        self._parameters.update({'trend': None})

    def _regressor_terms(self, t):
        reg_idx, reg_terms = super()._regressor_terms(t)

        # add trend
        reg_terms.append(t)
        reg_idx.update({'trend': self.f_order * 2 + 1})

        return reg_idx, reg_terms


class LinearBrokenTrendFourier(LinearTrendFourier):
    """Linear regression with a broken trend and Fourier terms.

    The Fourier terms allow capturing the periodic variability in the
    time-series. This model also allows capturing a sudden change in
    trend at a given (a-priori known or unknown) point of
    discontinuity.

    See Also
    --------
    :class:`~trendfit.models.LinearTrendFourier`

    Notes
    -----
    The model is defined as follows (see [1]_):

    .. math::

       y_t = \alpha + \beta t + \delta D_{t, T_1} + F_t + \epsilon_t

    where :math:`\alpha` is the intercept, :math:`\beta` is the slope,
    :math:`\epsilon_t` is the error term, :math:`F_t` is the nth-order
    approximated Fourier series, i.e.,

    .. math::

       F_t = \sum{j=1}{M} a_j \cos(2 j \pi t) + b_j \sin(2 j \pi t)

    and :math:`\delta D_{t, T_1}` is a term introduced for
    representing a break in the slope, with :math:`\delta` being the
    change in slope, :math:`T_1` the location of the slope discontinuity
    and :math:`D_{t, T_1}` a dummy variable given by:

    .. math::
       :nowrap:

       D_{t, T_1} = \left\{
                \begin{array}{ll}
                  0 & \mathrm{if} t \leq T_1\\
                  t - T_1 & \mathrm{if} t \gt T_1
                \end{array}
                    \right\}

    When :math:`T_1` is defined a-priori, the model is fitted to
    :math:`\{t, y_t\}` data using ordinary least squares
    (OLS). Otherwise, the optimization algorithm implemented in
    :func:`scipy.optimize.dual_annealing` is used to fit :math:`T_1`,
    using the sum of squares of residuals returned by OLS as the
    objective function.

    References
    ----------
    .. [1] M. Friedrich, E. Beutner, H. Reuvers, S. Smeekes, J-P. Urbain,
    W. Bader, B. Franco, B. Lejeune, and E. Mahieu, 2019. "Nonparametric
    estimation and bootstrap inference on trends in atmospheric time series:
    an application to ethane" arXiv:1903.05403v1

    """
    def __init__(self, f_order=3, t_break=None, opt_bounds=None,
                 **opt_kwargs):
        """

        Parameters
        ----------
        f_order : int, optional
            Finite order of the truncated Fourier series (default=3). Set
            it to zero there's no periodic variability in the time series.
        t_break : float, optional
            Location of the trend discontinuity. If None (default), the
            location will be estimated when fitting the model to data.
        opt_bounds : tuple, optional
            limits of the search range for estimating ``t_break`` with
            :func:`scipy.optimize.dual_annealing`.
            If None (default), the whole range of the input time series
            is used.
        **opt_kwargs : key=value pairs, optional
            Keyword arguments that will be passed to
            :func:`scipy.optimize.dual_annealing`.

        """
        super().__init__(f_order)

        self._fit_t_break = t_break is None
        self._parameters['t_break'] = t_break

        self._opt_bounds = opt_bounds
        self._opt_kwargs = opt_kwargs

    def _regressor_terms(self, t, t_break):
        reg_idx, reg_terms = super()._regressor_terms(t)

        # add trend breaking point
        reg_terms.append(np.where(t > t_break, t - t_break, 0.))
        reg_idx.update({'trend_change': self.f_order * 2 + 2})

        return reg_idx, reg_terms

    def _fit(self, t, y):

        def solve_for_location(t_break):
            # solve system with a-priori t_break value

            reg_idx, reg_terms = self._regressor_terms(t, t_break)

            ssr = self._solve_lstsq(t, y, reg_idx, reg_terms)

            # system solving issues with t_break near bounds
            if not len(ssr):
                return np.inf
            else:
                return ssr[0]

        if self._fit_t_break:
            if self._opt_bounds is None:
                bounds = [(t[1], t[-1])]
            else:
                bounds = [self._opt_bounds]

            kwargs = {'maxiter': 500}
            kwargs.update(self._opt_kwargs)

            res = dual_annealing(solve_for_location, bounds, **kwargs)

            self._parameters['t_break'] = res.x[0]

        # rerun lstsq to properly set other parameter values
        reg_idx, reg_terms = self._regressor_terms(
            t, self._parameters['t_break']
        )
        res_lstsq = self._solve_lstsq(t, y, reg_idx, reg_terms)

        if self._fit_t_break:
            return res
        else:
            return res_lstsq

    def _predict(self, t):
        reg_idx, reg_terms = self._regressor_terms(
            t, self._parameters['t_break']
        )

        return self._compute_y(t, reg_idx, reg_terms)


def epanechnikov_kernel(u):
    mask = np.abs(u) <= 1.
    weight = 3 / 4 * (1 - u**2)

    return weight * mask


class KernelTrend(BaseEstimator):
    """Non-parametric kernel regression.

    """
    valid_kernels = {
        'epanechnikov': epanechnikov_kernel
    }

    def __init__(self, kernel='epanechnikov', bandwidth=None):

        super().__init__()

        if isinstance(kernel, str) and kernel in self.valid_kernels:
            self.kernel_func = self.valid_kernels[kernel]
        elif callable(kernel):
            self.kernel_func = kernel
        else:
            raise ValueError("Invalid kernel {}".format(kernel))

        self._parameters = {
            'bandwidth': bandwidth,
        }

    def _local_constant(self, t, y, tau=None):
        if tau is None:
            tau = t

        pairwise_dists = np.subtract.outer(tau, t)

        k = self.kernel_func(pairwise_dists / self._parameters['bandwidth'])

        return k @ y / np.sum(k, axis=1)

    def _fit(self, t, y):
        self._t_scaled = (t - t[0]) / (t[-1] - t[0])

        self._parameters['trend'] = self._local_constant(self._t_scaled, y)

    def _predict(self, t):
        t_scaled = (t - self._t[0]) / (self._t[-1] - self._t[0])

        m_hat = self._local_constant(self._t_scaled, self._y, t_scaled)

        return m_hat
