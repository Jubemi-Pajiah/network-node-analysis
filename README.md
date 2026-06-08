# Pipe Network Analysis Using the Nodal Head Correction Method

This repository contains the single shared solver, the validation
against EPANET, the figures and tables, and an interactive web application, all built from one solver module.

The nodal head correction method is solved by Newton-Raphson with a sparse
Jacobian and `scipy.sparse.linalg.spsolve` (SuperLU).

## Repository layout

```
solver/                  the single solver (used by the scripts AND the web app)
  network.py             Node, Pipe, Network data structures + validation
  headloss.py            Hazen-Williams and Darcy-Weisbach (Swamee-Jain) models
  core.py                the Newton-Raphson nodal head correction algorithm
  networks.py            the three test networks
  serialize.py           JSON <-> Network conversion for the web app
plotting.py              shared figure code (used by figures AND the web app)
analysis.py              runs solver + EPANET on all networks, caches results.json
validation/
  epanet_bridge.py       reproduces a network in EPANET via WNTR
  validate.py            prints comparison tables and the maximum % error
  hand_check.py          independent Hardy Cross check of the small network
figures/generate_figures.py   generates all required PNG figures
app/                     Flask web application
results/results.json     cached numerical results (regenerated on demand)
```

## Quick start (local)

```bash
pip install -r requirements.txt

# 1. validate the solver against EPANET (prints the maximum % error)
python -m validation.validate

# 2. independent hand-check of the small network (Hardy Cross)
python -m validation.hand_check

# 3. generate every figure (PNGs land in figures/)
python -m figures.generate_figures

# 5. run the web application locally
python app/app.py            # then open http://127.0.0.1:5000
# or, with the production server:
gunicorn app.app:app         # Linux/macOS; serves on http://127.0.0.1:8000
```

The web page loads pre-populated with the Single-loop network and solves it
immediately. Edit any node or pipe value, choose a head-loss model, set the
tolerance and iteration limit, then click **Solve network**; all outputs and
both diagrams update. A preset selector loads the three test networks.

## Deploying on Render (free web service)

This repository includes `render.yaml`, so Render can configure the service
automatically (Blueprint). To deploy manually:

1. Push this repository to GitHub.
2. In the Render dashboard choose **New > Web Service** and connect the repo.
3. Set:
   - **Environment:** Python 3
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn app.app:app`
   - **Instance type:** Free
4. Create the service. Render installs the dependencies and starts Gunicorn;
   the public URL it assigns serves the application.

Note: `gunicorn` is a Unix WSGI server and is used on Render (Linux). On
Windows, run the app locally with `python app/app.py`.

## How the pieces stay consistent

There is exactly one solver (`solver/`). The figures, the validation
and the web application all import it; none re-implements the
algorithm. The figures shown in the browser are produced by the same
`plotting.py` used for the static figures, and every number
quoted here is read from `results/results.json`, which is
produced directly by the solver and EPANET.

## References

- Rossman, L. A. (2000). *EPANET 2: Users manual*. U.S. Environmental
  Protection Agency.
- Klise, K. A., Bynum, M., Moriarty, D., & Murray, R. (2017). A software
  framework for assessing the resilience of drinking water systems to
  disasters with an example earthquake case study. *Environmental Modelling &
  Software, 95*, 420-431.
- Swamee, P. K., & Jain, A. K. (1976). Explicit equations for pipe-flow
  problems. *Journal of the Hydraulics Division, 102*(5), 657-664.
