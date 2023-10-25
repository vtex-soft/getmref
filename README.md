# GetMRef

## Table of Contents

* [About](#about)
* [Usage](#usage)
* [Input data](#input-data)
* [Requesting the AMS MR database](#requesting-the-ams-mr-database)
* [Output data](#output-data)
* [Bug reports](#bug-reports)

## About

GetMRef adds an MR number[^1] for each given bibliography reference that has been 
found in the American Mathematical Society Mathematical Reviews (AMS MR) database[^2].
Additionally, matches found in the database can be saved in one of 4 possible 
formats: `tex`, `bibtex`, `amsrefs` and `html`. 
Therefore, one can check if user provided references contain full and correct data. 
Also GetMRef can be used as a reference formatting tool 
(user citation keys from original references will be inserted).
 
GetMRef sends requests to the database through AMS BatchMref tool[^3].  
One can send requests directly using AMS MRef tool with graphical interface[^4].

[^1]: <https://mathscinet.ams.org/mathscinet/help/getitem.html#findmr>
[^2]: <https://mathscinet.ams.org/mathscinet/index.html>
[^3]: <https://mathscinet.ams.org/batchmref>
[^4]: <https://mathscinet.ams.org/mathscinet-mref>

## Usage

To run GetMRef on Windows OS:
```bash
getmref.exe <input_file>
```

To see all options with short description:
```bash
getmref.exe --help
```

On Linux or Mac OS run the included Python script:
```bash
python3 getmref.py <input file>
```
or 
```bash
python3 getmref.py --help
```
(please see [Python script requirements](#python-script-requirements) section below).

### Python script requirements

Python script can be run directly, for that Python 3.9 or newer is required[^5].

For an option `--enc=auto` the Universal Encoding Detector library[^6],
written by Mark Pilgrim and maintained by Dan Blanchard, is required.

[^5]: <https://docs.python.org/3.9/using/index.html>
[^6]: <https://pypi.python.org/pypi/chardet>


## Input data

Input has to be a file containing bibliography references without MR number.
References with MR number already present will be skipped.  

Only the following reference formats are recognized:  
* Basic LaTeX `\bibitem[<optional info>]{<cite_key>} <reference text>`, e.g.,

  ```tex
  \begin{thebibliography}{9}
  
  \bibitem{lamport94}
      Leslie Lamport,
      \emph{\LaTeX: a document preparation system},
      Addison Wesley, Massachusetts,
      2nd edition,
      1994.
  
  \end{thebibliography}
  ```
  
* [BibTeX](https://ctan.org/pkg/bibtex) `@<reference_type>{<cite_key>, <key_n>=<value_n>}`, e.g.,  

  ```tex
  @article{greenwade93,
      author  = {"George D. Greenwade"},
      title   = {"The {C}omprehensive {T}ex {A}rchive {N}etwork ({CTAN})"},
      year    = {"1993"},
      journal = {"TUGBoat"},
      volume  = {"14"},
      number  = {"3"},
      pages   = {"342--351"},
      }
  ```
  
* [AMSRefs](https://ctan.org/pkg/amsrefs) `\bib{<cite_key>}{<reference_type>}{<key_n>=<value_n>}`, e.g.,

  ```tex
  \begin{bibdiv}
  \begin{biblist}
  
  \bib{Sokal96}{article}{
      title={Trangressing the boundaries},
      subtitle={Toward a transformative hermeneutics of quantum gravity},
      author={Sokal, Alan},
      journal={Social Text},
      volume={46/47},
      date={1996},
      pages={217--252}
      }
  
  \end{biblist}
  \end{bibdiv}
  ```

An input file may contain all these reference formats *at once*. 
Reference format type is determined automatically and the resulting MR number is 
formatted and inserted according to this type.    

By default, at first GetMRef looks for `thebibliography` or `biblist` environment 
and processes only the references *inside* this environment. 
If no bibliography reference has been found inside an environment 
or an environment hasn't been found at all, all references found in the file 
will be processed. The first step may be skipped using the `--nobibenv` option. 

User may provide an appropriate encoding for the input file reading with an 
option `--enc=<encoding>`. By default, it is set to `latin1`. In order to 
automatically determine the encoding, this option can be set to `auto`. 
For this to work the Universal Encoding Detector library[^5], written by 
Mark Pilgrim and maintained by Dan Blanchard, is required.

## Requesting the AMS MR database 
 
User provided references are sent to <https://mathscinet.ams.org/batchmref> as XML string:
```xml
<?xml version = "1.0" encoding = "UTF-8"?>
<mref_batch>
  <mref_item outtype="amsref|bibtex|html|tex">
    <inref>string</inref>
    <myid>1</myid>
  </mref_item>
  ...
  <mref_item outtype="amsref|bibtex|html|tex">
    <inref>string</inref>
    <myid>99</myid>
  </mref_item>
</mref_batch>
```
One request to the AMS MR database can contain up to 100 references 
(`mref_item` elements). User may use an option `--itemno=<integer>` (default is
set to 100) to (only) *decrease* this limit. 
This value *does not limit* how many references can be in the input file.

The result of the request is the same XML string with the `mrid`, 
`outref` and `matches` fields appended for each `mref_item`:
```xml
<?xml version = "1.0" encoding = "UTF-8"?>
<mref_batch>
  <mref_item outtype="amsref|bibtex|html|tex">
    <inref>string</inref>
    <myid>1</myid>
    <mrid>string</mrid>
    <outref>string</outref>
    <matches>0|1</matches>
  </mref_item>
  ...
  <mref_item outtype="amsref|bibtex|html|tex">
    <inref>string</inref>
    <myid>99</myid>
    <mrid>string</mrid>
    <outref>string</outref>
    <matches>0|1</matches>
  </mref_item>
</mref_batch>
```

While testing GetMRef, it has been noticed that in order to get correct results,
there is a need for a short pause after each query to the AMS MR database. 
Otherwise many references that exist in the database will be returned as not 
found. Also, there is a possibility that fields with new information will 
be appended to a different `mref_item`. 
According to <http://www.ams.org/robots.txt> there is a "Crawl-Delay: 10". 
Tests have confirmed that 10s delay between requests to the AMD MR database is 
an optimal choice and it is the default setting. In order to change the delay time, 
one can use an option `--wait=<integer>`.

## Output data

GetMRef output depends on user provided references format(s) (see the [Input data](#input-data) section) 
and the requested output format.

If reference has been found in the AMS MR database, an MR number will be added to 
each such reference according to its original formatting in the following way:

* `\MR{<number>}` for Basic LaTeX format  
* `MRNUMBER={<number>}` for BibTeX format  
* `review={\MR{<number>}}` for AMSRefs format   

Additional output files will be generated according to the requested output format 
(use an option `--format=<tex|bibtex|amsrefs|html|ims>`).
The AMS MR database provides the following output format types: 
`tex`, `bibtex`, `amsrefs`, `html`.
For each format type there will be the following additional files generated, 
containing references in the requested format:

* file `<input_filename>.getmref.data` for `tex` and `amsrefs` formats  
* file `<input_filename>.getmref.html` for `html` format  
* files `<input_filename>.getmref.bib` and `<input_file>.getmref.aux` for 
  `bibtex` and `ims` formats. (The latter is an extension of the `bibtex` format.) 
  
  Additionally user may use `--bibstyle=<BibTeX style>` option (default is `plain`), 
  which will be inserted into generated *.aux file as `\bibstyle{<BibTeX style>}`. 
  For more information please consult the BibTeX documentation.
  
## Bug reports

Please submit bug report or feature requests at [github](https://github.com/vtex-soft/getmref/issues) page.

---
