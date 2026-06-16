import pandas as pd
import joblib
import matplotlib.pyplot as plt

# Load model
model = joblib.load("artifacts/models/best_gold_model.joblib")

# Load feature names
features = joblib.load("artifacts/models/gold_model_features.joblib")

# Create dataframe
importance_df = pd.DataFrame({
    "feature": features,
    "importance": model.feature_importances_
})

importance_df = importance_df.sort_values(
    by="importance",
    ascending=False
)

print("\nTop 15 Features")
print(importance_df.head(15))

# Save CSV
importance_df.to_csv(
    "data/reports/feature_importance.csv",
    index=False
)

# Plot
plt.figure(figsize=(10, 6))

top_features = importance_df.head(15)

plt.barh(
    top_features["feature"],
    top_features["importance"]
)

plt.xlabel("Importance")
plt.ylabel("Feature")
plt.title("Top 15 Feature Importance")

plt.tight_layout()

plt.savefig(
    "data/reports/feature_importance.png"
)

plt.show()