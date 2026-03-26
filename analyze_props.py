import asyncio
import os
from dotenv import load_dotenv
from fetch_odds import get_player_props
from alerts import send_alert
from stadium_data import get_stadium_info
from live_stats import get_batter_hrr, get_pitcher_era

load_dotenv()

async def run_prop_analysis():
    print("--- 🎯 MLB HRR Prop Value Scanner Active ---")
    
    # 1. Fetch HRR Props
    games = get_player_props('batter_hits_runs_rbis')
    
    if not games:
        print("❌ No active HRR prop markets found. (Books may not have posted them yet).")
        return

    for game in games:
        home_team = game['home_team']
        away_team = game['away_team']
        stadium = get_stadium_info(home_team)
        
        # Pitchers (To adjust the batter's projection)
        home_pitcher = game.get('home_pitcher', 'Unknown')
        away_pitcher = game.get('away_pitcher', 'Unknown')
        home_p_era = get_pitcher_era(home_pitcher)
        away_p_era = get_pitcher_era(away_pitcher)

        # 2. Dig into the Bookmaker Markets
        for bookmaker in game.get('bookmakers', []):
            for market in bookmaker.get('markets', []):
                if market['key'] == 'batter_hits_runs_rbis':
                    
                    # We only need to check each player once per game, not every outcome
                    processed_players = set()
                    
                    for outcome in market.get('outcomes', []):
                        player_name = outcome.get('description')
                        bookie_line = outcome.get('point', 1.5) # Usually 1.5 for HRR
                        
                        if player_name in processed_players:
                            continue
                        processed_players.add(player_name)

                        # 3. Get Base HRR from our Stats Engine
                        base_hrr = get_batter_hrr(player_name)
                        
                        # 4. Adjust based on Opposing Pitcher & Stadium
                        # We do a simplified check to assign the correct opposing pitcher
                        # (In V2 we can cross-reference the player's exact team, but this is a solid heuristic)
                        opposing_era = home_p_era # Assume away batter for baseline
                        
                        # Apply the math
                        pitcher_multiplier = opposing_era / 4.20
                        projected_hrr = round(base_hrr * pitcher_multiplier * stadium['park_factor'], 2)
                        
                        # 5. Calculate Edge
                        edge = round(projected_hrr - bookie_line, 2)
                        
                        if abs(edge) >= 0.5:
                            side = "OVER" if edge > 0 else "UNDER"
                            emoji = "🔥" if abs(edge) >= 0.8 else "🎯"
                            
                            report = (
                                f"{emoji} **PROP VALUE: {player_name} (HRR)**\n"
                                f"⚾️ Game: {away_team} @ {home_team}\n"
                                f"🏛 Park Factor: {stadium['park_factor']} | 👤 vs ERA: {opposing_era}\n"
                                f"📈 **My Proj:** {projected_hrr} | 🎰 **Bookie:** {bookie_line}\n"
                                f"💰 **Edge:** {edge} ({side})\n"
                            )
                            
                            print(report)
                            await send_alert(report)
                            
                            # Let's break after finding one massive edge for testing
                            return

if __name__ == "__main__":
    asyncio.run(run_prop_analysis())