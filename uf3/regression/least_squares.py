import numpy as np
from uf3.regression import regularize


class WeightedLinearModel:
    """
    -Perform weighted linear regression with scikit-learn compatible functions
    -Fit model given x, y, optional weights, and optional regularizer
    """
    def __init__(self,
                 regularizer=None,
                 fixed_tuples=None,
                 bspline_config=None,
                 **regularize_params):
        """
        Args:
            bspline_config (bspline.BsplineConfig)
            regularizer (np.ndarray): regularization matrix.
            regularize_params: arguments to generate regularizer matrix
                if regularizer is not provided.
        """
        self.coefficients = None
        self.fixed_tuples = fixed_tuples

        if regularizer is not None:
            self.regularizer = regularizer
        else:
            if regularize_params is None:
                raise ValueError(
                    "Neither regularizer nor regularizer parameters provided.")
            if bspline_config is None:
                raise ValueError(
                    "BSplineConfig not provided to generate regularizer.")
            reg = bspline_config.get_regularization_matrix(**regularize_params)
            self.regularizer = reg

    def fit(self, x, y, weights=None):
        """
        Args:
            x (np.ndarray): input matrix of shape (n_samples, n_features).
            y (np.ndarray): output vector of length n_samples.
            weights (np.ndarray): sample weights (optional).
        """
        solution = weighted_least_squares(x,
                                          y,
                                          weights=weights,
                                          regularizer=self.regularizer,
                                          fixed=self.fixed_tuples)
        self.coefficients = solution

    def predict(self, x):
        """
        Args:
            x (np.ndarray): input matrix of shape (n_samples, n_features).

        Returns:
            predictions (np.ndarray): vector of predictions.
        """
        predictions = np.dot(x, self.coefficients)
        return predictions

    def score(self, x, y, weights=None):
        """
        Args:
            x (np.ndarray): input matrix of shape (n_samples, n_features).
            y (np.ndarray): output vector of length n_samples.
            weights (np.ndarray): sample weights (optional).

        Returns:
            score (float): negative weighted root-mean-square-error.
        """
        n_features = len(x[0])
        if weights is not None:
            w_matrix = np.eye(n_features) * np.sqrt(weights)
            x = np.dot(w_matrix, x)
            y = np.dot(w_matrix, y)
        predictions = self.predict(x)
        score = -np.sqrt(np.mean(np.subtract(y, predictions) ** 2))
        return score


def linear_least_squares(x, y):
    """
    Solves the linear least-squares problem Ax=y. Regularizer matrix
        should be concatenated to x and zero-values padded to y.

    Args:
        x (np.ndarray): input matrix of shape (n_samples, n_features).
        y (np.ndarray): output vector of length n_samples.

    Returns:
        solution (np.ndarray): coefficients.
    """
    xTx = np.dot(x.T, x)
    xTx_inv = np.linalg.inv(xTx)
    solution = np.dot(np.dot(xTx_inv, x.T), y)
    return solution


def weighted_least_squares(x,
                           y,
                           weights=None,
                           regularizer=None,
                           fixed=None):
    """
    Solves the linear least-squares problem with optional square regularizer
        matrix and optional weighting.

    Args:
        x (np.ndarray): input matrix.
        y (np.ndarray): output vector.
        weights (np.ndarray): sample weights (optional).
        regularizer (np.ndarray)
        fixed (list): list of tuples of indices and coefficients to fix
            before fitting. Useful for ensuring smooth cutoffs or
            fixing multiplicative coefficients.
            e.g. fix=[(0, 10), (15, 0)] fixes the first coefficient (idx=0)
            to 10 and the sixteenth coefficient (idx=15) to 0.

    Returns:
        solution (np.ndarray): coefficients.
        predictions (list of np.ndarray): predictions.
    """
    n_feats = len(x[0])
    if regularizer is not None:
        if regularizer.shape != (n_feats, n_feats):
            raise ValueError(
                "Expected regularizer shape: {} x {}".format(n_feats, n_feats))

    if weights is not None:
        if len(weights) != len(x):
            raise ValueError(
                'Number of weights does not match number of samples.')
        if not np.all(weights >= 0):
            raise ValueError('Negative weights provided.')
        w = np.sqrt(weights)
        x_fit = np.multiply(x.copy().T, w).T
        y_fit = np.multiply(y.copy(), w)
    else:
        x_fit = x.copy()  # copy in preparation for modifying with fixed coeff.
        y_fit = y.copy()

    if fixed is not None:
        fixed = np.array(fixed)
        fixed_colidx = fixed[:, 0]
        fixed_coefficients = fixed[:, 1]
        x_fit, y_fit, mask = preprocess_fixed_coefficients(x_fit,
                                                           y_fit,
                                                           fixed_coefficients,
                                                           fixed_colidx)
        regularizer = regularizer[mask, :][:, mask]

    if regularizer is not None:
        reg_zeros = np.zeros(len(regularizer))
        x_fit = np.concatenate([x_fit, regularizer])
        y_fit = np.concatenate([y_fit, reg_zeros])
    solution = linear_least_squares(x_fit, y_fit)

    if fixed is None:
        return solution
    else:
        coefficients = np.zeros(n_feats)
        np.put_along_axis(coefficients, mask, solution, 0)
        np.put_along_axis(coefficients, fixed_colidx, fixed_coefficients, 0)
        return coefficients


def preprocess_fixed_coefficients(x,
                                  y,
                                  fixed_coefficients,
                                  fixed_colidx):
    """
    
    Args:
        x (np.ndarray): feature array.
        y (np.ndarray): target vector.
        fixed_coefficients (np.ndarray): coefficient values to fix.
        fixed_colidx (np.ndarray): column indices of fixed coefficients.

    Returns:
        x (np.ndarray): feature array with fixed_colidx removed.
        y (np.ndarray): target vector with fixed column contributes subtracted.
        mask (np.ndarray): indices of remaining columns in x.
    """
    n_feats = len(x[0])
    mask = np.setdiff1d(np.arange(n_feats), fixed_colidx)
    x_fixed = x[:, fixed_colidx]
    x = x[:, mask]
    y = np.subtract(y, np.dot(x_fixed, fixed_coefficients))
    return x, y, mask


def postprocess_coefficients(coefficients, core_hardness=1.1):
    """
    Postprocess 2B coefficients to enforce repulsive core.

    Args:
        coefficients (np.ndarray): vector of 2B coefficients.
        core_hardness (float): multiplicative factor for curvature.

    Returns:
        coefficients (np.ndarray): new vector of coefficients.
    """
    gradient = np.gradient(coefficients)  # finite-difference gradient
    decreasing_check = (np.sign(gradient) < 0)  # boolean vector
    decreasing_point = np.argmax(decreasing_check)
    slope = gradient[decreasing_point]

    coefficients = np.array(coefficients)
    for i in np.arange(decreasing_point - 1)[::-1]:
        right = coefficients[i + 1]
        coefficients[i] = right - slope * core_hardness
    return coefficients