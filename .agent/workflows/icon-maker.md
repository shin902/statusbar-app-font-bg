---
description: アイコンのsvg画像を作成します。
---

入力の画像をsvg画像のコードで再現してください。簡素化は絶対しないで

# 作成時の注意点
<svg xmlns="http://www.w3.org/2000/svg" xml:space="preserve" style="fill-rule:evenodd;clip-rule:evenodd;stroke-linejoin:round;stroke-miterlimit:2" viewBox="0 0 100 100"></svg>
このタグで囲むこと

- ナレッジのsvgファイルのイメージに完璧に合わせて、デザインを作ること。白と黒の2色の配色にして

- ロゴの大きさは100%にして、余白をなくすようにすること



保存時:
mappings/に':antigravity:'のように、アプリの名前を:で囲んで、MacとLinuxで使われているプロセス名を|でつなげて記述してください
例：`mappings/:brave_browser:`
"Brave Browser" | "brave-browser"

svgs/には、同じファイル名に拡張子.svgを付けて、上の指示に沿ったsvg画像を保存してください。
作成するファイルの例：`svgs/:brave_browser:.svg`