import asyncio
import os
from dotenv import load_dotenv
from fetch_odds import get_mlb_odds, get_market_line
from model import calculate_projected_run_total
from alerts import send_alert
from stadium_data import get_stadium_info
from live_stats import get_live_rpg_map, get_pitcher_era
from weather import get_weather

# Load .env at the very start
load_dotenv()

async def run_analysis():
    print("--- 🚀 MLB 2-Way Projection Engine Active ---")
    
    # 1. Load Global Data
    live_stats = get_live_rpg_map()
    games = get_mlb_odds()
    
    if not games:
        print("❌ No active MLB games found.")
        return

    for game in games:
        home_team_name = game['home_team']
        away_team_name = game['away_team']
        
        # 2. Get Stadium & Team Info
        home_info = get_stadium_info(home_team_name)
        away_info = get_stadium_info(away_team_name)
        
        # 3. Identify Pitchers (Away vs Home)
        home_pitcher = game.get('home_pitcher', 'Unknown')
        away_pitcher = game.get('away_pitcher', 'Unknown')

        # 4. Get Weather for the Home Stadium
        weather = get_weather(home_info['city'])
        temp, w_speed, w_dir = (weather['temp'], weather['wind_speed'], weather['wind_dir']) if weather else (70, 0, 'neutral')

        # --- BATTLE 1: AWAY OFFENSE vs HOME PITCHER ---
        away_offense_rpg = live_stats.get(away_info['abbr'], 4.5)
        home_pitcher_era = get_pitcher_era(home_pitcher)
        away_base = (away_offense_rpg + home_pitcher_era) / 2
        
        away_projected_score = calculate_projected_run_total(
            base_avg=away_base,
            ballpark_factor=home_info['park_factor'],
            temp=temp, 
            wind_speed=w_speed, 
            wind_dir=w_dir
        )

        # --- BATTLE 2: HOME OFFENSE vs AWAY PITCHER ---
        home_offense_rpg = live_stats.get(home_info['abbr'], 4.5)
        away_pitcher_era = get_pitcher_era(away_pitcher)
        home_base = (home_offense_rpg + away_pitcher_era) / 2
        
        home_projected_score = calculate_projected_run_total(
            base_avg=home_base,
            ballpark_factor=home_info['park_factor'],
            temp=temp, 
            wind_speed=w_speed, 
            wind_dir=w_dir
        )

        # 5. THE FINAL TOTAL
        my_total_projection = round(away_projected_score + home_projected_score, 2)
        bookie_line = get_market_line(game, 'totals')
        edge = round(my_total_projection - bookie_line, 2)
        
        # 6. Formatting the Alert
        side = "OVER" if edge > 0 else "UNDER"
        emoji = "🔥" if abs(edge) >= 0.8 else "📊"
        
        report = (
            f"{emoji} **GAME TOTAL: {away_team_name} @ {home_team_name}**\n"
            f"👤 **Matchup:** {away_pitcher} vs {home_pitcher}\n"
            f"📈 **My Projection:** {my_total_projection} ({away_projected_score} - {home_projected_score})\n"
            f"🎰 **Bookie Line:** {bookie_line}\n"
            f"💰 **Edge:** {edge} runs ({side})\n"
            f"🌡 {temp}°F | Wind: {w_speed}mph {w_dir}"
        )

        print(f"Verified: {away_team_name} @ {home_team_name} | Edge: {edge}")
        await send_alert(report)
        
        # Stop after one for testing purposes
        break

if __name__ == "__main__":
    asyncio.run(run_analysis())