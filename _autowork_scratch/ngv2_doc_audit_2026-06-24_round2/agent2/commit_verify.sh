#!/bin/bash
# Verify every commit SHA referenced in the docs exists in the named repo
NG=/home/xnihil0zer0/NobleGreedv2
JM=/home/xnihil0zer0/JanusMaskJR
echo "===== NGv2 referenced SHAs ====="
for sha in eb113f5 fe8384c cad0a6e 057310f 5ab82c2 aa718c9 c2f7486 e10ee24 80722d6 2a83d06 ce89dc4 ed91619 fa6a069 a970fc7 2a11250 731e9b2 ac14367 9261edc baf77b4 3f9af36 dc07188 9a712e6 e6a7f38 e4280e1 a27ca22 59b8b15 4f299a1 203d007; do
  if git -C $NG cat-file -t $sha >/dev/null 2>&1; then
    printf "NGv2  %-9s OK   %s\n" "$sha" "$(git -C $NG log -1 --format='%ci %s' $sha 2>/dev/null | cut -c1-90)"
  else
    printf "NGv2  %-9s ABSENT\n" "$sha"
  fi
done
echo
echo "===== JM referenced SHAs ====="
for sha in 8ef60e9 a400a38 2049f78 b0d6999 afea293 b47e8ad 3f9af36 fc8167a 0795605; do
  if git -C $JM cat-file -t $sha >/dev/null 2>&1; then
    printf "JM    %-9s OK   %s\n" "$sha" "$(git -C $JM log -1 --format='%ci %s' $sha 2>/dev/null | cut -c1-90)"
  else
    printf "JM    %-9s ABSENT\n" "$sha"
  fi
done
