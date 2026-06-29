leverage https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep and karpathy's https://github.com/karpathy/autoresearch as examples to leverage. 

goal: build an auto agentic-looping research program that finds and tests integrates and improves on features for a feature engineering project on ML algo for sub-prime credit lending. 


what i want to build that my customer's talking about:


"Goal: Auto Feature Generator

Use LLM to auto generate features based on given context, build Objective

The goal is to leverage an LLM to automatically generate features based on provided context, followed by building the model, evaluating results, logging outcomes, and iterating through a user-defined number of loops.

Inputs Provided by User

Base Raw Table and Base Feature Table
Model and Pre-Processing.py script
Context, skills, and specific instructions


Process Workflow

Agentic Step: Feature Engineering – The LLM analyzes statistics and context to identify potential new features (adding only a few per iteration). It updates the original Python script to generate a new feature table (e.g., iter1_feature_set) and logs these details into a Feature_Log_table. All artifacts must be registered to ensure the exact process used for each table is known.
Tool Step: Model Training &amp; Evaluation – The system utilizes the new features to retrain the model and generate performance scores such as AUC and KS. These metrics are then recorded in the Feature_log_table.
Success Validation – If the revised model shows performance improvements, the feature set is marked as a success; otherwise, it is flagged as a failure.
Iterative Learning – The cycle repeats with a new set of features, informed by historical attempts in the Feature_log_table to learn from previous successes and failures. The number of cycles is determined by the user.


The process does not need to be fully autonomous; the LLM can be invoked as needed throughout the workflow."

please follow the spirit here


rules: BRING IN REAL CREDIT LENDING DATA. NOT SYNTHETIC WHEREVER POSSIBLE. 