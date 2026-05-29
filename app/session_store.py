import pandas as pd
from typing import Dict

# In-memory dictionary storing pandas DataFrames by session_id
session_store: Dict[str, pd.DataFrame] = {}
