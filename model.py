
import math
from scipy.stats import poisson

def calculate_projected_run_total(base_avg, ballpark_factor, temp, wind_speed, wind_dir):
	"""
	Adjusts a base scoring average based on external variables.
	ballpark_factor: 1.0 is neutral, 1.1 is 'hitter friendly' (+10%)
	temp: 70 degrees is neutral.
	wind_dir: 'in', 'out', or 'neutral'
	"""
    
	projected_total = base_avg
    
	# 1. Apply Ballpark Factor
	projected_total *= ballpark_factor
    
	# 2. Temperature Adjustment (Balls fly further in heat)
	# Roughly 0.33% change per degree away from 70
	temp_adj = 1 + ((temp - 70) * 0.0033)
	projected_total *= temp_adj
    
	# 3. Wind Adjustment
	if wind_dir == 'out':
		# Wind blowing out adds ~1% per mph
		projected_total *= (1 + (wind_speed * 0.01))
	elif wind_dir == 'in':
		# Wind blowing in subtracts ~1% per mph
		projected_total *= (1 - (wind_speed * 0.01))
        
	return round(projected_total, 2)

def get_win_probability(my_projection, bookie_line):
	"""
	Uses Poisson to see how likely the 'Over' is.
	"""
	# Probability of scoring MORE than the bookie's line
	prob_over = 1 - poisson.cdf(bookie_line, my_projection)
	return round(prob_over * 100, 2)

# TEST THE BRAIN
if __name__ == "__main__":
	# Example: Dodgers at Coors Field (High ballpark factor)
	# Base average is 4.5 runs, 1.2 ballpark factor, 67 degrees, 10mph wind OUT
	my_runs = calculate_projected_run_total(4.5, 1.2, 67, 10, 'out')
    
	print(f"My Projected Runs: {my_runs}")
    
	# If the bookie set the line at 5.5 runs:
	chance_of_over = get_win_probability(my_runs, 5.5)
	print(f"Chance of hitting the Over 5.5: {chance_of_over}%")
