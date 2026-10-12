from mcp.server.fastmcp import FastMCP
mcp = FastMCP("Leetcoach")
@mcp.tool()
def hello(name:str):
    """say hello"""
@mcp.tool()
def add(a: int,b:int):
    """ Add two number"""
    return a +b    
@mcp.tool()
def multiply(a:int,b:int):
    """ Multiply two numbers"""
    return a * b
if __name__  == "__main__":
    mcp.run()
