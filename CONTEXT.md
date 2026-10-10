# BMW Customer Feedback

Customer feedback on BMW vehicles, broken down into aspects so product owners can see what owners praise, struggle with, want, or report as broken, per model and engine type.

## Language

### Feedback

**Feedback**:
One customer's written comment about one vehicle, identified by its Feedback Explorer ID. It counts once no matter how many aspects it has.
_Avoid_: Row, record, review, entry

**Verbatim**:
The customer's own text of a feedback, exactly as written.
_Avoid_: Comment, raw text, translated feedback

**Source**:
The channel a feedback came in through (Source A–D). What each source stands for is not yet confirmed.
_Avoid_: Origin, provider, channel

**Source Document**:
A file, database table, or web page that a cited fact comes from. A whole feedback dataset is one source document.
_Avoid_: Source, document, dataset

### Vehicle

**Brand**:
The vehicle's make as the source names it, e.g. "BMW".
_Avoid_: Make, manufacturer

**Derivate**:
The vehicle's model code, e.g. F70, G60, G70.
_Avoid_: Model, model code, series, e-code

**Sales Description**:
The vehicle's marketing name, e.g. "BMW 1 Series".
_Avoid_: Model name, product

**Engine Type**:
The vehicle's drivetrain: ICE, PHEV, or BEV, or unknown when the source gives none. "BEVE" means BEV.
_Avoid_: Powertrain, fuel type

### Geography

**Country**:
The country a feedback came from, as a two-letter ISO code, e.g. DE. It says where the feedback was given, not where the vehicle is sold.
_Avoid_: Market, location

**Region**:
A named group of countries an analysis is scoped to. EU groups the EU member countries that feedback actually came from; every other country is its own region, e.g. US, CN.
_Avoid_: Market, area

### Aspects

**Aspect**:
One thing a feedback says about one part of the vehicle. A feedback has zero or more aspects, and each one carries its own feedback type, buckets, and sentiment.
_Avoid_: Topic, tag, label, mention

**Feedback Type**:
The source system's own classification of an aspect: Likes, Difficult to Use, Wants, or Defect. It belongs to the aspect, so one feedback can be both Likes and Defect. An inferred aspect takes the feedback type the source gave its unlabelled feedback.
_Avoid_: Feedback category, kind

**VFC Label**:
A curated, human-assigned classification from BMW's VFC taxonomy, made of an aspect term and an aspect label.
_Avoid_: Tag, annotation, class

**Aspect Term**:
The VFC level-2 name: the specific component or feature being discussed, e.g. "Touch screen, operation".
_Avoid_: Level 2, component, feature, subcategory, VFC category

**Aspect Label**:
The VFC level-3 name: what was said about the aspect term, e.g. "Not user-friendly".
_Avoid_: Level 3, problem, finding, VFC issue

**Unlabelled Feedback**:
A feedback with no usable VFC label (blank or "no_class_found"). Its aspects can only be inferred.
_Avoid_: Unclassified feedback, uncategorised

### Buckets

**VFC Category**:
One of 16 coarse buckets an aspect term belongs to, e.g. "Infotainment & Connectivity". Each aspect term maps to exactly one.
_Avoid_: Category group, area, domain, system

**Issue Type**:
One of 11 coarse buckets saying what kind of thing an aspect is, e.g. Malfunction, Usability Difficulty, Feature Request, Praise. Each aspect label maps to exactly one.
_Avoid_: Problem type, complaint type, defect type

**Unclassified**:
The bucket used when no VFC category or issue type fits. It is a bucket value, not a missing label: a labelled aspect can be Unclassified, and an unlabelled feedback can produce aspects that are not.
_Avoid_: Other, misc, unknown

**Taxonomy Mapping**:
The reviewed list assigning every aspect term to a VFC category and every aspect label to an issue type. It is the single place a bucketing decision is made or corrected.
_Avoid_: Classification, lookup, ontology

### Provenance

**Curated Aspect**:
An aspect taken from a VFC label assigned by a human. Only the label is human: its buckets come from the taxonomy mapping and its sentiment score from a model.
_Avoid_: Labelled aspect, ground truth

**Inferred Aspect**:
An aspect a model extracted from the verbatim of an unlabelled feedback, constrained to the same VFC categories and issue types.
_Avoid_: Predicted aspect, AI aspect, synthetic aspect

**Quote**:
The exact passage of the verbatim that supports an inferred aspect. An inferred aspect whose passage does not appear word for word in the verbatim has no quote. Curated aspects have none.
_Avoid_: Snippet, excerpt, evidence

### Sentiment

**Sentiment**:
Whether an aspect is Positive, Negative, or Neutral, decided by its issue type alone: Praise is Positive; Feature Request and Unclassified are Neutral; every other issue type is Negative. A customer wanting something is a Feature Request, so demand is Neutral, not a sentiment of its own.
_Avoid_: Polarity, tone, mood, demand

**Intensity**:
How strongly the customer expresses an aspect, from 0 to 1, regardless of direction.
_Avoid_: Strength, confidence, magnitude

**Sentiment Score**:
Intensity signed by sentiment, from −1 to +1; always 0 for Neutral aspects. It ranks aspects within a sentiment; it never decides the sentiment.
_Avoid_: Rating, score, NPS
