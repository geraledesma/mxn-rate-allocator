# mx-yield-allocator

Optimization engine for allocating savings across Mexican yield products with tiered rates.

## What this project does

This project builds the mathematical and code foundation for a Mexican yield allocator focused on products with:

- daily liquidity
- tiered interest rates
- optimal allocation across products

The current V1 model solves a linear optimization problem that maximizes total expected interest over a fixed comparison horizon, while enforcing strict sequential tranche filling within each product.

## Current scope

- daily-liquidity products only
- one common comparison horizon
- tiered-rate allocation
- notebook demo and Python optimizer module

## Planned extensions

- IPAB and Prosofipo coverage constraints
- multiple products per institution
- operational conditions and eligibility rules
- user preference constraints
- support for multiple liquidity horizons

## Project structure

```text
notebooks/
src/
```

## Status

Early-stage research and prototype repository.

## License

MIT

