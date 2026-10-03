# Oakhaven

A tiny game used to prove the literate pipeline. The prose you are reading is
part of the same file as the code, which is the whole point of convention 8.

## The world

<details><summary>Locations</summary>

```game
location "Oakhaven Village":
  "Timber halls ring a muddy square."
  has inn, shop
  north to "Whispering Woods"

location "Whispering Woods":
  "Ancient oaks crowd the path."
  south to "Oakhaven Village"
  spawns "Goblin Scout"
```

</details>

Prose between blocks is ignored by the tangler, and so is a fenced block in
another language:

```python
print("not game source")
```

## Inhabitants

```game
monster "Goblin Scout":
  12 hp, 3 str, 7 agi, 2 int
  drops 2 to 5 gold
  drops "Goblin Ear"
```
