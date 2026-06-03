import pandas as pd

prices = pd.read_csv("data/raw/entsoe/prices.csv")
load = pd.read_csv("data/raw/entsoe/load.csv")
generation = pd.read_csv("data/raw/entsoe/generation.csv")

print("\nPRICES")
print(prices.head())
print(prices.shape)
print(prices.columns)

print("\nLOAD")
print(load.head())
print(load.shape)
print(load.columns)

print("\nGENERATION")
print(generation.head())
print(generation.shape)
print(generation.columns)