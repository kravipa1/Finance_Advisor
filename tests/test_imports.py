def test_imports_smoke():
    import numpy as np
    import pandas as pd

    # sanity
    assert np.array([1, 2, 3]).sum() == 6
    assert pd.DataFrame({"a": [1]}).shape == (1, 1)
