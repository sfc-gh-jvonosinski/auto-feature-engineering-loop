-- Training and Evaluation Stored Procedure
-- Fixed evaluator: trains XGBoost, returns AUC/KS/Gini + feature importances
-- This procedure is NEVER modified by the agent loop.

CREATE OR REPLACE PROCEDURE AUTO_FEATURE_ENG.CREDIT_RISK.TRAIN_AND_EVALUATE(
    FEATURE_TABLE_NAME VARCHAR,
    ITERATION_ID INT,
    RUN_ID VARCHAR
)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'xgboost', 'scikit-learn', 'numpy', 'scipy')
HANDLER = 'run'
AS $$
import json
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score
from scipy.stats import ks_2samp
import xgboost as xgb

def run(session, feature_table_name, iteration_id, run_id):
    # Load data
    df = session.table(feature_table_name).to_pandas()
    
    target = 'SERIOUSDLQIN2YRS'
    exclude = ['ID', target]
    feature_cols = [c for c in df.columns if c not in exclude]
    
    X = df[feature_cols].fillna(0).astype(float)
    y = df[target].astype(int)
    
    # Stratified split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )
    
    # Train XGBoost with class imbalance handling
    pos_count = int(y_train.sum())
    neg_count = int(len(y_train) - pos_count)
    scale_pos = neg_count / max(pos_count, 1)
    
    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.1,
        scale_pos_weight=scale_pos,
        random_state=42,
        eval_metric='auc',
        verbosity=0,
        use_label_encoder=False
    )
    model.fit(X_train, y_train)
    
    # Evaluate
    y_prob = model.predict_proba(X_test)[:, 1]
    auc = float(roc_auc_score(y_test, y_prob))
    
    # KS statistic
    pos_probs = y_prob[y_test == 1]
    neg_probs = y_prob[y_test == 0]
    ks = float(ks_2samp(pos_probs, neg_probs).statistic)
    
    gini = 2 * auc - 1
    
    # Feature importances (top 20)
    importances = dict(zip(
        feature_cols,
        [float(x) for x in model.feature_importances_]
    ))
    top_features = dict(sorted(importances.items(), key=lambda x: x[1], reverse=True)[:20])
    
    return {
        "auc": round(auc, 6),
        "ks_stat": round(ks, 6),
        "gini": round(gini, 6),
        "n_features": len(feature_cols),
        "feature_importances": top_features,
        "iteration_id": iteration_id,
        "run_id": run_id
    }
$$;
