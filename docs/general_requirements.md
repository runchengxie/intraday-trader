# CQF FINAL PROJECTS

> **课堂参考**：本文档来源于课堂作业，仅作参考；实际项目流程与贡献指南以仓库 README 为准。

*by Dr Richard Diamond, PhD CQF ARPM*

## Preparation

* Start with FP brief, Key Readings and collecting necessary data.
  * *Additional Material*
  * Use data sources named for each topic, e.g., yfinance for equities data.
  * Make reasonable assumptions and generate synthetic data. It is up to you to source data and decide on features based on guidance provided.
    * *spreads, rates, IVs.*
  * Topic CR, assume hypothetical CDS spreads and compute Corr from equity returns.
    * *TDS Web.*

* Plan your own course of implementation/study design. Make simple flowcharts and lists.
  * Refer to CQF Lectures. On DL/ML/DN topics in particular do extra reading on methods.

## Code Adoption

A. You can adopt code for specific tasks, but not to submit a scripted coded solution or slightly changed CQF Python Lab code. Amend code for your purpose, not copy/paste.

B. Where pricing or techniques maths is given – that signals to implement from the first principles. Where computation is overly elaborate: quant judgement to use ready libraries. Typically is where optimisation involved.

* *RNN or Convolution CNN-LSTM*

C. Welcome to implement complex numerical methods vs. use of ready solution – if able to.

* *Num methods in DL are about not over training hyperparams for CNN*

## Numerical Techniques

Implement as necessary, numerical techniques from the first principles.

**What to code:** pricing formulae, Black-Litterman formulae, SDE Monte-Carlo schemes, matrix form regression, Engle-Granger, interpolation, Cholesky, t-copula formula, CDS bootstrap, features computation...

**Use ready solutions for:** most of deep learning/classification tasks (eg, don't recode optimisation search for NN coefficients!), low latency RNs, kernel density (obtaining CDF), multivariate cointegration...

* *but correct layering in CNN-LSTM (example)*

* *RNN limitations in regard to time series sequences.*

## Project Report

* **(Ch 1)** Introduction with problem statement, describing design, main data and a coded numerical techniques table.

* **(Ch 2)** As full as possible mathematical description of the models employed as well as numerical methods. Remember accuracy and convergence!

  * *vs. ChX at end, discussing - hyperparam search, Kernel tricks - accuracy, F1scores, epochs / EP.*

* **(Ch 3-4 Results | Analysis)** Present results presented using a plenty of tables and figures, which must be interpreted not just thrown at the reader.

* **(Ch 5 Conclusions)** Pros and cons of a model and its implementation, together with possible improvements.

  * *"say what you have said"*

## Project Report (cont)

* Demonstrate 'the specials' of your implementation: own research, own coding of complex methods, use of the industrial-strength libraries of C++, Python.

* Instructions on how to compile/run, if not common Python/R. The code must be thoroughly tested and well-documented, however no need to over-comment the code.

> *Design can be "with code", stemming from IPYNB format*
> *But can be .py or .R or .cpp files as project + report.*
> *No need to code-annotate each line, each variable.*

## The Offering

* We will have a look at Topics in the main Project Brief.

* **Main Sources:** FP Brief, FP Workshop slides and Additional Files, FP Tutorials and distributed material.

* Electives come secondary, one exception is Topic AL Algo Trading. Electives can be watched at the stage of Analysis & Discussion write up.

## Submission Instructions

*Please follow:*

**FILE 1.** It's **absolutely necessary** to name and upload the project report as **ONE file** (pdf or html) with the two-letter project code, followed by your name as **registered** on CQF Portal.

* Examples: `TS_John Smith_REPORT.pdf` or `PC_Xiao Wang_REPORT.pdf`

* *(Note: `Nbconvert` is written, likely referring to a tool for converting notebooks to other formats).*

**FILE 2.** All other files, code and a pdf declaration (if not the front page) have to be uploaded as additional **ONE zip file**, for example `TS_John Smith_CODE.zip`.

* No unzipped `.py`, `.cpp` files. No files with generic names, e.g. `CODE.zip`, `FinalProject.zip`.

## Final Day

**Final Day as FP Brief.**

Don't Extend Your Luck!

> *There is no standard "extension 2 weeks"*
