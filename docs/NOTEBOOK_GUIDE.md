# How to Run the Demo Notebook

## Quick Start

```bash
cd /Users/gera.ledesma/Desktop/Projects/rate-allocator

# Install if not already done
pip install -e .

# Start Jupyter
jupyter notebook notebooks/demo.ipynb
```

## What's in the Notebook

### 6 Ready-to-Run Scenarios

1. **Small Allocation (25,000 MXN)**
   - Tests single tier allocation
   - Expected rate: ~15% (Nu's first tier)

2. **Medium Allocation (100,000 MXN)**
   - Tests multi-institution, multi-tier
   - Shows how allocator prioritizes higher rates

3. **Large Allocation (500,000 MXN)**
   - Tests full tier utilization
   - Effective rate decreases as we hit lower tiers

4. **Comparison Table**
   - See how effective rate changes with amount
   - Useful for understanding tier structure impact

5. **Custom Institutions**
   - Create your own institution setup
   - Test any rate structure you design

6. **Edge Cases**
   - Zero allocation
   - Tiny amounts
   - Exact tier boundaries
   - Very large amounts

### Interactive Cell

The last cell is yours to experiment:
```python
test_amount = 150_000  # <-- Change this
```

Run it as many times as you want with different amounts!

## What You'll See

For each test:
- **Effective rate**: Weighted average rate across all allocations
- **Expected return**: Annual return in currency
- **Allocation detail**: 
  - Which institution gets how much
  - Which tier each amount goes into
  - The rate for each tier

## Tips

- Start with Scenario 1 to understand the basics
- Run Scenario 4 to see rate degradation
- Use Scenario 5 to test your own ideas
- Use the interactive cell for quick experiments

**Ready to explore!** 🚀
