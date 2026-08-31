# Finance Basics for This Project

## The project goal

We are building a research lab for possible investing signals. It does not automatically buy stocks. It helps us test questions such as:

> Can a change in a company's SEC filing language help identify companies that may perform relatively better or worse later?

The project should answer this question honestly, save the evidence, and reject weak ideas.

## A stock and a return

A stock is a small ownership share in a company. If a stock goes from $100 to $110, its return is:

```text
return = (110 / 100) - 1 = 0.10 = 10%
```

## A factor and a factor score

A factor is a repeatable rule that gives companies a score. The score is a ranking signal, not a guaranteed prediction.

Example idea:

```text
Companies with worsening filing language receive lower scores.
Companies with improving filing language receive higher scores.
```

At the current project stage, the demo scores are made-up numbers used to test the software. Later, scores will be calculated from versioned, dated public data.

## What alpha means here

In plain language, alpha means value beyond simply following the overall market. A useful alpha factor should make high-scored companies perform better than low-scored companies often enough, after realistic costs and fair testing.

This is difficult. Most good-looking historical patterns are noise, accidental data leaks, or patterns that disappear after costs. The project is designed to detect those failures rather than hide them.

## Paper portfolio

A paper portfolio is a simulated portfolio. No money moves. We use it to ask what a simple strategy would have done in history.

The current demo uses a simple long/short construction:

- Long the highest-scored company: benefit if it rises.
- Short the lowest-scored company: benefit if it falls.
- Use equal-sized positive and negative positions so the example is less dependent on the whole market rising.

This is an educational starting point, not a production portfolio design.
