import pandas as pd

df = pd.read_csv("data/features/gold_model_features.csv")

print("Shape:", df.shape)

print("\nMissing values:")
print(df.isna().sum().sort_values(ascending=False))

print("\nDate range:")
print(df["timestamp"].min())
print(df["timestamp"].max())