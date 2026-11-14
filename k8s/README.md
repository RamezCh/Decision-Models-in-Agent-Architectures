# CLM-8B on the BHT cluster

`clm.yaml` runs CLM-8B on one A100 in namespace `vpdx3758`: a pod with the Qwen3-8B encoder (vLLM) and `clm-serve`, plus a 40 GiB disk so the model (~16 GB) is downloaded only once.

**Only you can reach it.** Both servers listen on `127.0.0.1` inside the pod, and there is no Service or Ingress. The only way in is `kubectl port-forward`, which needs the VPN and your cluster login.

## Use it (VPN connected)

```bash
kubectl apply -f k8s/clm.yaml                          # start
kubectl -n vpdx3758 get pod clm -w                     # wait for READY 1/1 (first start: download, a while)
kubectl -n vpdx3758 port-forward pod/clm 8700:8700     # keep this terminal open
```

Check it: http://127.0.0.1:8700/health should show `"embedder": true`. The demos use `CLM_BASE_URL=http://127.0.0.1:8700` from `.env`.

When you're done:

```bash
kubectl -n vpdx3758 delete pod clm                     # frees the GPU; the disk keeps the model
```

The cluster also deletes GPU pods that sit idle for over an hour, so a forgotten pod doesn't block the A100 for long. Start it again with the same `kubectl apply` line; it loads from the disk in a few minutes.

## If something goes wrong

* **Logs:** `kubectl -n vpdx3758 logs clm -f`
* **Stays `Pending`:** no free A100 right now. `kubectl -n vpdx3758 describe pod clm` shows why.
* **Remove everything, including the model:** `kubectl delete -f k8s/clm.yaml`
