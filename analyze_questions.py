import json
import re
from collections import Counter

def analyze():
    with open('questions.json', 'r') as f:
        data = json.load(f)
    
    with open('sample_questions.json', 'r') as f:
        samples = json.load(f)
    
    questions = data['questions']
    
    # Operation mappings
    op_keywords = {
        'sum': [
            'combined value', 'total value', 'aggregate', 'sum', 'total of all', 
            'combined total', 'final tally', 'cumulative figure', 'filter for anything at or over',
            'crossing the .* mark', 'clear the .* mark'
        ],
        'count': [
            'how many', 'count of', 'number of distinct', 'number of different', 
            'count of separate', 'how many different categories'
        ],
        'days': [
            'how many days', 'interval from', 'span from', 'days elapsed', 
            'count from .* to completion', 'elapsed period', 'days to completion', 'elapsed time'
        ],
        'percent': [
            'percentage', 'out of 100', 'collection percentage', 'share of', 
            'numerical value representing the share', 'out-of-100 figure'
        ],
        'rank_diff': [
            'largest .* exceed the second', 'difference between the largest .* and the second', 
            'surplus value separating our highest-value .* from the next', 'beats the one just behind it',
            'largest one exceeds the second', 'largest completed project exceeds the second'
        ],
        'financial_gap': [
            'gap between', 'shortfall between', 'difference in value between', 
            'amount we would need to bring in to hit', 'outstanding contract value .* to clear', 
            'unbilled remainder', 'missing amount between', 'delta between secured work and submitted claims',
            'how much more .* to clear the .* bar'
        ],
        'mean_median_diff': [
            'difference between the mean and the median', 'larger the average .* is than the median', 
            'rupee gap between avg and median', 'mean against the median', 'mean-median gap'
        ],
        'average': [
            'average size', 'mean size', 'mean volume', 'typical project scale', 
            'overall average', 'mean across'
        ],
        'temporal_aggregate': [
            'completed after that date', 'finished after that date', 'wrapped up after'
        ],
        'exclusion_aggregate': [
            'excluding', 'minus', 'once we remove', 'carve that out', 'stripped out', 
            'once we carve that out', 'exclude the .* segment'
        ],
        'year_diff': [
            'between 20.* and 20.*', 'movement in .* value was between', 
            'difference in .* between 20.* and 20.*', 'variance between .* 20.* number and their 20.* figure',
            'completed work values for .* in 20.* and 20.*', 'difference in completed work value between .* 20.* and 20.*',
            '20.* and 20.* completed work totals'
        ]
    }
    
    op_dist = Counter()
    trickiest = []
    
    for q in questions:
        text = q['question'].lower()
        found_op = 'unknown'
        
        for op, keywords in op_keywords.items():
            for kw in keywords:
                if re.search(kw, text):
                    found_op = op
                    break
            if found_op != 'unknown':
                break
        
        op_dist[found_op] += 1
        
        if len(text) > 250 or found_op == 'unknown' or 'mean and the median' in text or 'largest' in text and 'second' in text:
            trickiest.append(q['question'])

    print("--- Operation Distribution ---")
    for op, count in op_dist.most_common():
        print(f"{op}: {count}")
    
    print("\n--- Trickiest Questions (Sample) ---")
    for t in trickiest[:10]:
        print(f"- {t}")

    print("\n--- Phrasing Patterns ---")
    fillers = ['still getting my head around', 'pretty sure', 'just grabbing', 'lock the bid', 'submission cutoff', 'my recollection', 'getting my bearings', 'learning the ropes', 'finding my way', 'looks off on the first pass']
    filler_count = 0
    for q in questions:
        if any(f in q['question'].lower() for f in fillers):
            filler_count += 1
    print(f"Conversational filler found in {filler_count}/{len(questions)} questions.")

    print("\n--- Potential Blind Spots ---")
    year_range_count = sum(1 for q in questions if re.search(r'between 20\d{2} and 20\d{2}', q['question'].lower()))
    print(f"Year ranges: {year_range_count}")
    testimonial_count = sum(1 for q in questions if 'testimonial' in q['question'].lower())
    print(f"Testimonials: {testimonial_count}")

analyze()
