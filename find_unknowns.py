import json
import re

def find_unknowns():
    with open('questions.json', 'r') as f:
        data = json.load(f)
    
    op_keywords = {
        'sum': ['combined value', 'total value', 'aggregate', 'sum', 'total of all', 'combined total', 'final tally'],
        'count': ['how many', 'count of', 'number of distinct', 'number of different', 'count of separate'],
        'days': ['how many days', 'interval from', 'span from', 'days elapsed', 'count from .* to completion', 'elapsed period'],
        'percent': ['percentage', 'out of 100', 'collection percentage', 'share of', 'numerical value representing the share'],
        'rank_diff': ['largest .* exceed the second', 'difference between the largest .* and the second', 'surplus value separating our highest-value .* from the next', 'beats the one just behind it'],
        'financial_gap': ['gap between', 'shortfall between', 'difference in value between', 'amount we would need to bring in to hit', 'outstanding contract value .* to clear', 'unbilled remainder'],
        'mean_median_diff': ['difference between the mean and the median', 'larger the average .* is than the median', 'rupee gap between avg and median', 'mean against the median'],
        'average': ['average size', 'mean size'],
        'temporal_aggregate': ['completed after that date', 'finished after that date', 'wrapped up after'],
        'exclusion_aggregate': ['excluding', 'minus', 'once we remove', 'carve that out', 'stripped out', 'once we carve that out'],
        'year_diff': ['between 20.* and 20.*', 'movement in .* value was between', 'difference in .* between 20.* and 20.*']
    }
    
    questions = data['questions']
    unknowns = []
    
    for q in questions:
        text = q['question'].lower()
        found = False
        for op, keywords in op_keywords.items():
            for kw in keywords:
                if re.search(kw, text):
                    found = True
                    break
            if found: break
        if not found:
            unknowns.append(q['question'])
            
    for u in unknowns[:50]:
        print(u)

find_unknowns()
